"""Failure-first server session, exact fresh-proof and original preservation contracts."""

import copy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework_web import access
from apps.mufti_review.identity import IdentityUnavailable
from tests.casework import test_http as http

from . import integration, services
from .models import FreshProof, ProofUse, Session, SessionRevocation
from .test_support import CREDENTIALS, FEATURES, SessionFixture


@override_settings(**FEATURES)
class StaffSessionTests(SessionFixture, TransactionTestCase):
    def snapshot(self):
        return {
            m._meta.label: list(m.objects.order_by("pk").values())
            for m in apps.get_models()
            if m._meta.app_label not in {"staff_sessions", "casework_web"}
        }

    def test_explicit_default_off_and_missing_policy_runtime_or_directory_fail_closed(self):
        for key, value in (
            ("FATWA_STAFF_SESSIONS_ENABLED", False),
            ("FATWA_STAFF_SESSION_AUTHORITY", None),
            ("FATWA_STAFF_SESSION_RUNTIME_EPOCH", None),
            ("FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with self.subTest(key=key), override_settings(**{key: value}):
                self.assertEqual(self.client.get("/casework/sessions/").status_code, 403)
                self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.authority.denied.add("USE")
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)

    def test_native_fresh_proof_revokes_exact_other_session_preserves_sources_and_current_session(
        self,
    ):
        before = self.snapshot()
        page = self.fresh()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(SessionRevocation.objects.count(), 0)
        self.assertEqual(FreshProof.objects.count(), 1)
        self.assertEqual(self.revoke(page).status_code, 303)
        self.assertEqual(self.other_client.get("/casework/staff/").status_code, 403)
        self.assertEqual(self.client.get("/casework/staff/").status_code, 200)
        self.assertEqual((SessionRevocation.objects.count(), ProofUse.objects.count()), (1, 1))
        self.assertEqual(self.snapshot(), before)
        for model in (Session, SessionRevocation, FreshProof, ProofUse):
            self.assertNotIn(CREDENTIALS["mufti"], repr(list(model.objects.values())))

    def test_logout_revokes_on_server_so_copied_signed_cookie_and_csrf_cannot_return(self):
        copied = copy.deepcopy(self.client.cookies)
        before = self.snapshot()
        result = http.post(self.client, "/casework/staff/logout/", {}, self.page)
        self.assertEqual(result.status_code, 303, result.content)
        self.client.cookies = copied
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.assertEqual(SessionRevocation.objects.get().reason, "LOGOUT")
        self.assertEqual(self.snapshot(), before)

    def test_cross_actor_or_wrong_credentials_do_not_issue_fresh_proof(self):
        other, page = self.login("other")
        denied = self.select(other, self.session_id(self.client))
        self.assertEqual(denied.status_code, 403)
        selected = self.select()
        for credential in (CREDENTIALS["other"], "wrong-credential" * 3):
            self.assertEqual(self.fresh(selected, credential).status_code, 403)
        self.assertEqual(FreshProof.objects.count(), 0)
        self.assertEqual(SessionRevocation.objects.count(), 0)

    def test_fresh_proof_binds_operation_resource_session_and_is_one_use(self):
        page = self.fresh()
        proof = FreshProof.objects.get()
        self.assertEqual(proof.operation, "REVOKE_SESSION")
        self.assertEqual(str(proof.session_id), self.session_id(self.client))
        self.assertEqual(str(proof.target_id), self.session_id(self.other_client))
        third, _ = self.login()
        forged = http.post(
            third,
            "/casework/sessions/",
            {
                "action": "revoke",
                "target_id": http.hidden(page, "target_id"),
                "ticket": http.hidden(page, "ticket"),
                "proof_id": str(proof.id),
            },
            third.get("/casework/sessions/"),
        )
        self.assertEqual(forged.status_code, 403)
        self.assertEqual(self.revoke(page).status_code, 303)
        self.assertEqual(self.revoke(page).status_code, 403)
        self.assertEqual(ProofUse.objects.count(), 1)

    def test_expiry_policy_identity_and_session_revocation_after_verifier_prevent_proof_save(self):
        actor = self.directory.identities["mufti"]
        for kind in ("policy", "identity", "session", "deadline"):
            selected = self.select()
            patches = []

            def hook():
                if kind == "policy":
                    self.authority.denied.add("REVOKE")
                elif kind == "identity":
                    self.directory.identities["mufti"] = replace(actor, active=False)
                elif kind == "session":
                    services._append_revocation(
                        Session.objects.get(pk=self.session_id(self.client)),
                        Session.objects.get(pk=self.session_id(self.client)),
                        "LOGOUT",
                        None,
                    )
                else:
                    p = patch(
                        "apps.staff_sessions.services.timezone.now",
                        return_value=actor.valid_until + timedelta(seconds=1),
                    )
                    p.start()
                    patches.append(p)

            self.directory.hook = hook
            try:
                self.assertEqual(self.fresh(selected).status_code, 403)
            finally:
                for p in patches:
                    p.stop()
            self.directory.hook = None
            self.authority.denied.clear()
            self.directory.identities["mufti"] = actor
            self.assertEqual(FreshProof.objects.count(), 0)
            if kind == "session":
                self.client, self.page = self.login()

    def test_ended_request_binding_cannot_escape_to_a_background_job(self):
        with integration.request_context():
            request = self.page.wsgi_request
            actor = access.current_staff(request, self.directory)
            proxy = access.RequestDirectory(
                self.directory, actor, authenticated_provider_id=self.directory.provider_id
            )
            self.assertEqual(proxy.resolve(actor.subject_id).subject_id, actor.subject_id)
        with self.assertRaises(IdentityUnavailable):
            proxy.resolve(actor.subject_id)

    def test_runtime_rotation_and_recovery_database_identity_reject_restored_sessions(self):
        with override_settings(
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="synthetic-session-runtime-generation-0002"
        ):
            self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        with patch.object(
            services, "database_identity", return_value="different-restored-owned-database"
        ):
            self.assertEqual(self.client.get("/casework/staff/").status_code, 403)

    def test_sql_audit_rows_cannot_be_changed_deleted_or_forged(self):
        self.revoke(self.fresh())
        for model in (Session, SessionRevocation, FreshProof, ProofUse):
            row = model.objects.first()
            for change in (
                lambda: model.objects.filter(pk=row.pk).update(digest="0" * 64),
                lambda: model.objects.filter(pk=row.pk).delete(),
            ):
                with (
                    self.subTest(model=model.__name__),
                    self.assertRaises(IntegrityError),
                    transaction.atomic(),
                ):
                    change()
        self.assertEqual(SessionRevocation.objects.count(), 1)

    def test_revocation_between_cookie_and_core_service_stops_new_answer(self):
        before = self.snapshot()
        real = access.current_staff

        def revoke(*args, **kwargs):
            actor = real(*args, **kwargs)
            row = Session.objects.get(pk=self.session_id(self.client))
            services._append_revocation(row, row, "LOGOUT", None)
            return actor

        with patch("apps.casework_web.views.current_staff", side_effect=revoke):
            result = http.post(
                self.client,
                "/casework/staff/",
                {
                    "action": "draft",
                    "case_ref": self.receipt["public_ref"],
                    "revision": "1",
                    "evidence_version": "1",
                    "text": "لا يحفظ بعد الإبطال",
                },
                self.page,
            )
        self.assertIn(result.status_code, (403, 409))
        self.assertEqual(before, self.snapshot())

    def test_expired_proof_and_changed_policy_require_a_new_human_verification(self):
        page = self.fresh()
        proof = FreshProof.objects.get()
        with patch(
            "apps.staff_sessions.services.timezone.now",
            return_value=proof.expires_at + timedelta(seconds=1),
        ):
            self.assertEqual(self.revoke(page).status_code, 403)
        self.authority.fresh_seconds = 30
        self.assertEqual(self.revoke(page).status_code, 403)
        self.assertEqual(ProofUse.objects.count(), 0)

    def test_missing_csrf_get_duplicate_or_unregistered_action_cannot_revoke(self):
        self.assertEqual(self.client.get("/casework/sessions/?action=revoke").status_code, 400)
        self.assertEqual(
            self.client.post("/casework/sessions/", {"action": "revoke"}).status_code, 403
        )
        for action in ("WRITE_ANSWER", "APPROVE", "MFA_ENROLL", "ADMIN_GRANT"):
            result = http.post(self.client, "/casework/sessions/", {"action": action}, self.page)
            self.assertEqual(result.status_code, 400)
        self.assertEqual(SessionRevocation.objects.count(), 0)

    def test_hung_verifier_has_one_slot_bounded_wait_no_late_proof_or_replayed_result(self):
        from threading import Event
        from time import monotonic

        from . import execution

        entered, release, exited = Event(), Event(), Event()
        selected = self.select()
        original = self.directory.authenticate_fresh

        def blocked(credential, *, challenge):
            entered.set()
            try:
                release.wait(timeout=2)
                return original(credential, challenge=challenge)
            finally:
                exited.set()

        invoke = execution.invoke
        with (
            patch.object(self.directory, "authenticate_fresh", side_effect=blocked),
            patch.object(
                execution,
                "invoke",
                side_effect=lambda *a, **k: invoke(*a, **{**k, "timeout": 0.02}),
            ),
        ):
            try:
                started = monotonic()
                self.assertEqual(self.fresh(selected).status_code, 403)
                self.assertLess(monotonic() - started, 1)
                self.assertTrue(entered.is_set())
                self.assertEqual(self.fresh(selected).status_code, 403)
                self.authority.denied.add("REVOKE")
            finally:
                release.set()
                self.assertTrue(exited.wait(timeout=1))
        self.assertEqual(FreshProof.objects.count(), 0)
        self.authority.denied.clear()
        fresh = self.fresh(self.select())
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(FreshProof.objects.count(), 1)

    def test_actual_organizer_admin_session_has_no_implicit_revoke_grant_and_honors_revocation(
        self,
    ):
        import json

        from django.test import Client

        from apps.operational_workspace import access as ops

        from .test_support import operational_authority

        with override_settings(
            FATWA_OPERATIONAL_WORKSPACE_ENABLED=True,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=operational_authority(self.receipt),
        ):
            client = Client(
                enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
            )
            page = client.get("/casework/operations/login/")
            response = http.post(
                client, "/casework/operations/login/", {"credential": CREDENTIALS["admin"]}, page
            )
            self.assertEqual(response.status_code, 303, response.content)
            page = client.get("/casework/operations/sessions/")
            self.assertEqual(page.status_code, 200, page.content)
            admin_id = json.loads(page.wsgi_request.get_signed_cookie(ops.COOKIE, salt=ops.SALT))[
                "session_id"
            ]
            self.assertEqual(Session.objects.get(pk=admin_id).role, "ORGANIZER_ADMIN")
            self.assertEqual(client.get("/casework/operations/").status_code, 200)
            target_id = self.session_id(self.other_client)
            denied = http.post(
                client,
                "/casework/operations/sessions/",
                {"action": "select", "target_id": target_id},
                page,
            )
            self.assertEqual(denied.status_code, 403)
            self.authority.admin_targets.add(target_id)
            page = client.get("/casework/operations/sessions/")
            selected = http.post(
                client,
                "/casework/operations/sessions/",
                {"action": "select", "target_id": target_id},
                page,
            )
            self.assertEqual(selected.status_code, 200, selected.content)
            proof = http.post(
                client,
                "/casework/operations/sessions/",
                {
                    "action": "reauthenticate",
                    "target_id": target_id,
                    "ticket": http.hidden(selected, "ticket"),
                    "credential": CREDENTIALS["admin"],
                },
                selected,
            )
            self.assertEqual(proof.status_code, 200, proof.content)
            revoked = http.post(
                client,
                "/casework/operations/sessions/",
                {
                    "action": "revoke",
                    "target_id": target_id,
                    "ticket": http.hidden(proof, "ticket"),
                    "proof_id": http.hidden(proof, "proof_id"),
                },
                proof,
            )
            self.assertEqual(revoked.status_code, 303, revoked.content)
            self.assertEqual(self.other_client.get("/casework/staff/").status_code, 403)
            self.assertEqual(client.get("/casework/operations/").status_code, 200)
            cookie = copy.deepcopy(client.cookies)
            response = http.post(
                client,
                "/casework/operations/logout/",
                {},
                client.get("/casework/operations/sessions/"),
            )
            self.assertEqual(response.status_code, 303, response.content)
            client.cookies = cookie
            self.assertEqual(client.get("/casework/operations/").status_code, 409)
            self.assertEqual(
                SessionRevocation.objects.get(session_id=admin_id).by_session_id,
                Session.objects.get(pk=admin_id).id,
            )

    def test_denied_logout_cannot_report_success_without_server_revocation(self):
        self.authority.denied.add("USE")
        response = http.post(self.client, "/casework/staff/logout/", {}, self.page)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SessionRevocation.objects.count(), 0)
        self.authority.denied.clear()
        self.assertEqual(
            http.post(self.client, "/casework/staff/logout/", {}, self.page).status_code, 303
        )
        self.assertEqual(SessionRevocation.objects.count(), 1)

    def test_verifier_replay_fabricated_challenge_or_method_never_creates_proof(self):
        from .authority import FreshResult

        actor = self.directory.identities["mufti"]
        for fault in ("challenge", "old", "future", "method", "identity", "missing"):
            selected = self.select()

            def forged(credential, *, challenge):
                if fault == "missing":
                    raise RuntimeError("private diagnostic forbidden")
                return FreshResult(
                    replace(actor, subject_id="other") if fault == "identity" else actor,
                    "invented" if fault == "challenge" else challenge,
                    timezone.now()
                    + timedelta(seconds=-30 if fault == "old" else 30 if fault == "future" else 0),
                    "invented" if fault == "method" else self.directory.fresh_method_id,
                )

            with patch.object(self.directory, "authenticate_fresh", side_effect=forged):
                self.assertEqual(self.fresh(selected).status_code, 403)
            self.assertEqual(FreshProof.objects.count(), 0)
            self.assertEqual(self.client.get("/casework/staff/").status_code, 200)

    def test_explicit_policy_can_allow_confirmation_without_implying_fresh_proof_or_mfa(self):
        self.authority.required = False
        page = self.select()
        self.assertEqual(http.hidden(page, "proof_id"), "")
        self.assertEqual(self.revoke(page).status_code, 303)
        self.assertEqual(FreshProof.objects.count(), 0)
        self.assertEqual(ProofUse.objects.count(), 0)
        self.assertEqual(SessionRevocation.objects.count(), 1)

    def test_current_policy_revocation_during_native_render_suppresses_the_result(self):
        from . import views

        render = views.render
        before = self.snapshot()

        def revoke_after_render(*args, **kwargs):
            response = render(*args, **kwargs)
            self.authority.denied.add("USE")
            return response

        with patch.object(views, "render", side_effect=revoke_after_render):
            result = self.client.get("/casework/sessions/")
        self.assertEqual(result.status_code, 403)
        self.assertNotIn(self.session_id(self.other_client), result.content.decode())
        self.assertEqual(before, self.snapshot())
