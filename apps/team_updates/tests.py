"""Scoped inbox behavior over real synthetic PostgreSQL cases and native forms."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlencode

from django.db import DatabaseError, close_old_connections, connections, transaction
from django.test import override_settings

from apps.casework import services as casework
from apps.casework.models import CaseEvent
from tests.casework import test_http as contracts
from tests.casework.test_http import hidden, post

from .models import SeenUpdate
from .services import mark_seen


@override_settings(ROOT_URLCONF="apps.team_updates.urls")
class InboxTests(contracts.CaseworkHTTPTests):
    def setup_case(self):
        case, token, _, _, _ = self.intake("PRIVATE SYNTHETIC QUESTION")
        self.directory.grant(case.public_ref)
        return case, token, self.login()

    def seen(self, page, row=None, **overrides):
        row = row or page.context["updates"][0]
        return post(self.client, "/casework/staff/", {
            "action": "updates_seen", "case_ref": row["case_ref"],
            "sequence": row["sequence"], "proof": row["proof"], **overrides,
        }, page)

    def test_seen_is_explicit_idempotent_and_does_not_modify_case(self):
        case, _, page = self.setup_case()
        before = casework.read_case(case_id=case.pk, subject_id=self.directory.current.subject_id,
                                    provider=self.directory, synthetic_fixtures_only=True)
        self.assertEqual(page.context["unread"], 1)
        self.assertContains(page, case.events.get().created_at.strftime("%Y-%m-%d %H:%M"))
        self.assertNotContains(page, "PRIVATE SYNTHETIC QUESTION")
        self.client.get("/casework/staff/")
        self.open_case(case, page)
        self.assertEqual(SeenUpdate.objects.count(), 0)
        result = self.seen(page)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context["unread"], 0)
        first = SeenUpdate.objects.get()
        self.assertEqual(self.seen(page).status_code, 200)
        self.assertEqual(SeenUpdate.objects.count(), 1)
        self.assertEqual(SeenUpdate.objects.get().seen_at, first.seen_at)
        after = casework.read_case(case_id=case.pk, subject_id=self.directory.current.subject_id,
                                   provider=self.directory, synthetic_fixtures_only=True)
        self.assertEqual(after, before)
        self.assertEqual(CaseEvent.objects.filter(case=case).count(), 1)

    def test_new_followup_stays_unread_when_older_display_is_acknowledged(self):
        case, token, old_page = self.setup_case()
        casework.add_followup(token=token, text="PRIVATE NEW FACTS", expected_revision=1,
                              synthetic_fixtures_only=True)
        page = self.seen(old_page)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["unread"], 1)
        self.assertEqual(page.context["updates"][0]["kind"], "FOLLOWUP")
        self.assertEqual(page.context["updates"][0]["evidence_version"], 2)
        self.assertNotContains(page, "PRIVATE NEW FACTS")
        case.refresh_from_db()
        self.assertEqual(case.stage, "UNDER_REVIEW")
        self.assertIsNone(case.approved_answer_id)

    def test_seen_state_is_independent_between_staff_and_identity_providers(self):
        _, _, page = self.setup_case()
        self.seen(page)
        self.directory.current = replace(self.directory.current, subject_id="second-mufti")
        page = self.login()
        self.assertEqual(page.context["unread"], 1)
        self.seen(page)
        self.assertEqual(SeenUpdate.objects.count(), 2)
        self.directory.provider_id = "different-provider"
        page = self.login()
        self.assertEqual(page.context["unread"], 1)
        self.seen(page)
        self.assertEqual(SeenUpdate.objects.count(), 3)

    def test_scope_and_epoch_revocation_block_seen_without_receipt(self):
        case, _, page = self.setup_case()
        other, _, _, _, _ = self.intake("PRIVATE OTHER")
        self.assertEqual(self.seen(page, case_ref=other.public_ref).status_code, 403)
        self.directory.current = replace(self.directory.current, auth_epoch="revoked")
        self.assertEqual(self.seen(page).status_code, 403)
        self.assertEqual(SeenUpdate.objects.count(), 0)
        page = self.login()
        self.directory.grant(other.public_ref)
        self.assertEqual(self.seen(page, case_ref=case.public_ref).status_code, 403)
        page = self.client.get("/casework/staff/")
        self.assertEqual(page.context["total"], 1)
        self.assertNotContains(page, case.public_ref)

    def test_display_proof_cannot_be_reused_for_a_new_event_or_different_user(self):
        _, token, page = self.setup_case()
        row = page.context["updates"][0]
        casework.add_followup(token=token, text="new", expected_revision=1,
                              synthetic_fixtures_only=True)
        self.assertEqual(self.seen(page, sequence=2).status_code, 403)
        self.assertEqual(self.seen(page, proof="ع" * 64).status_code, 403)
        self.directory.current = replace(self.directory.current, subject_id="other-mufti")
        new_page = self.login()
        self.assertEqual(self.seen(new_page, row=row).status_code, 403)
        self.assertEqual(SeenUpdate.objects.count(), 0)

    def test_filters_history_and_pagination_are_read_only(self):
        case, token, page = self.setup_case()
        for revision in range(1, 23):
            casework.add_followup(token=token, text=f"synthetic update {revision}",
                                  expected_revision=revision, synthetic_fixtures_only=True)
        before = list(case.events.values_list("id", flat=True))
        page = post(self.client, "/casework/staff/", {
            "action": "updates_filter", "state": "all", "kind": "FOLLOWUP", "page": "1",
        }, page)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["matches"], 22)
        self.assertEqual(len(page.context["updates"]), 20)
        self.assertEqual(page.context["pages"], 2)
        self.assertTrue(page.context["updates"][1]["historical"])
        first = {row["sequence"] for row in page.context["updates"]}
        page = post(self.client, "/casework/staff/", {
            "action": "updates_filter", "state": "all", "kind": "FOLLOWUP", "page": "2",
        }, page)
        self.assertEqual(len(page.context["updates"]), 2)
        self.assertFalse(first & {row["sequence"] for row in page.context["updates"]})
        self.assertEqual(list(case.events.values_list("id", flat=True)), before)
        self.assertEqual(SeenUpdate.objects.count(), 0)

    def test_seen_marker_database_immutability_and_non_notification_event_denial(self):
        case, _, page = self.setup_case()
        self.seen(page)
        for action in (lambda: SeenUpdate.objects.update(auth_epoch="changed"),
                       lambda: SeenUpdate.objects.all().delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                action()
        casework.request_clarification(case_id=case.pk, subject_id=self.directory.current.subject_id,
                                        provider=self.directory, text="clarification",
                                        expected_revision=1, expected_evidence_version=1,
                                        synthetic_fixtures_only=True)
        with self.assertRaises(casework.CaseConflict):
            mark_seen(case_id=case.pk, sequence=2, subject_id=self.directory.current.subject_id,
                      provider=self.directory, synthetic_fixtures_only=True)
        self.assertEqual(SeenUpdate.objects.count(), 1)

    def test_csrf_duplicate_fields_and_role_payload_rejected(self):
        _, _, page = self.setup_case()
        values = {"action": "updates_filter", "state": "all", "kind": "all", "page": "1"}
        self.assertEqual(post(self.client, "/casework/staff/", {**values, "role": "MUFTI"}, page).status_code, 400)
        for invalid in ({"state": "unknown"}, {"kind": "APPROVE"}, {"page": "0"}):
            self.assertEqual(post(self.client, "/casework/staff/", {**values, **invalid}, page).status_code, 400)
        response = self.client.post("/casework/staff/", urlencode(values),
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 403)
        encoded = urlencode({**values, "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken")})
        response = self.client.post("/casework/staff/", encoded + "&state=unread",
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SeenUpdate.objects.count(), 0)

    def test_identity_change_at_locked_read_rejects_acknowledgement(self):
        from apps.casework_web.access import current_staff

        _, _, page = self.setup_case()

        def revoke_after_check(*args, **kwargs):
            identity = current_staff(*args, **kwargs)
            self.directory.current = replace(self.directory.current, auth_epoch="revoked")
            return identity

        with patch("apps.team_updates.views.current_staff", side_effect=revoke_after_check):
            response = self.seen(page)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SeenUpdate.objects.count(), 0)

    def test_concurrent_seen_marks_create_one_receipt(self):
        case, _, _ = self.setup_case()
        barrier = Barrier(2)

        def acknowledge():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return mark_seen(case_id=case.pk, sequence=1,
                                 subject_id=self.directory.current.subject_id,
                                 provider=self.directory, synthetic_fixtures_only=True)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: acknowledge(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(SeenUpdate.objects.count(), 1)
