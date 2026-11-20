"""Real PostgreSQL lifecycle, canonical composition and native form contracts."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_assignments.tests import AssignmentFixture
from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.delivery_queue.services import synthetic_queue_atomic
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import services, views
from .authority import LifecycleAuthority
from .models import LifecycleEvent

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.case_lifecycle.urls",
    "FATWA_CASE_LIFECYCLE_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
}


class Authority(LifecycleAuthority):
    def __init__(self, refs, provider_id):
        self.refs = set(refs)
        self.provider_id = provider_id
        self.denied = set()
        self.epoch = "lifecycle-fixture-1"
        self.callback = None

    def projection_epoch(self):
        return self.epoch

    def permits(self, **arguments):
        if self.callback is not None:
            self.callback(arguments)
        return (
            arguments["case_ref"] in self.refs
            and arguments["provider_id"] == self.provider_id
            and arguments["auth_epoch"] == "epoch-1"
            and arguments["action"] not in self.denied
            and (arguments["action"], arguments["case_ref"]) not in self.denied
        )

    def revoke(self, action, case_ref=None):
        self.denied.add((action, case_ref) if case_ref else action)
        self.epoch += ".next"


class Fixture(AssignmentFixture):
    def setUp(self):
        super().setUp()
        self.authority = Authority([self.receipt["public_ref"]], self.directory.provider_id)
        configured = override_settings(FATWA_CASE_LIFECYCLE_AUTHORITY=self.authority)
        configured.enable()
        self.addCleanup(configured.disable)

    def pins(self, receipt=None):
        row = Case.objects.get(pk=(receipt or self.receipt)["case_id"])
        return dict(expected_revision=row.revision, expected_evidence_version=row.evidence_version)

    def act(self, action, receipt=None, **changes):
        receipt = receipt or self.receipt
        common = self.common(receipt=receipt)
        values = dict(
            action=action,
            reason="سبب بشري اصطناعي " + action,
            expected_version=LifecycleEvent.objects.filter(case_id=receipt["case_id"]).count(),
            command_id=uuid.uuid4(),
            without_delivery=action == "CLOSE",
            **self.pins(receipt),
        )
        return services.command(**common, **{**values, **changes})

    def read(self, receipt=None):
        return services.desk(**self.common(receipt=receipt))

    def followup(self, *, receipt=None, text="تعقيب جديد صحيح"):
        receipt = receipt or self.receipt
        # The shared integration hook is deliberately coordinator-owned. This
        # exercise calls its actual helper inside the exact canonical transaction;
        # it remains idempotent once the coordinator installs the hook in _event.
        with synthetic_queue_atomic():
            current = Case.objects.get(pk=receipt["case_id"])
            result = cases.add_followup(
                token=receipt["token"],
                text=text,
                expected_revision=current.revision,
                synthetic_fixtures_only=True,
            )
            current.refresh_from_db()
            event = CaseEvent.objects.get(case=current, sequence=current.revision)
            services.record_followup(case=current, event=event)
            return result


@override_settings(**FEATURES)
class LifecycleTests(Fixture, TransactionTestCase):
    def test_close_archive_restore_reopen_preserve_canonical_facts_and_approval(self):
        self.approved()
        before = cases.read_case(**self.common())
        events = list(CaseEvent.objects.values())
        for action, state in [
            ("CLOSE", "CLOSED"),
            ("ARCHIVE", "ARCHIVED"),
            ("RESTORE", "CLOSED"),
            ("REOPEN", "OPEN"),
        ]:
            result = self.act(action)
            self.assertEqual(result["state"], state)
            self.assertEqual(self.read()["state"], state)
            self.assertEqual(cases.read_case(**self.common()), before)
        self.assertEqual(list(CaseEvent.objects.values()), events)
        self.assertEqual(LifecycleEvent.objects.count(), 4)
        self.assertEqual(self.read()["history"][-1]["no_delivery_claim"], True)

    def test_default_disabled_and_missing_authority_and_synthetic_gate(self):
        self.approved()
        for options in (
            {"FATWA_CASE_LIFECYCLE_ENABLED": False},
            {"FATWA_CASE_LIFECYCLE_AUTHORITY": None},
        ):
            with override_settings(**options), self.assertRaises(cases.CaseConflict):
                self.act("CLOSE")
        with self.assertRaises(cases.CaseConflict):
            services.desk(**{**self.common(), "synthetic_fixtures_only": False})
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_unanswered_draft_and_pending_clarification_cannot_close(self):
        with self.assertRaises(cases.CaseConflict):
            self.act("CLOSE")
        draft = cases.save_answer(**self.common(), **self.pins(), text="مسودة")
        with self.assertRaises(cases.CaseConflict):
            self.act("CLOSE")
        cases.record_decision(
            **self.common(), **self.pins(), answer_id=draft["answers"][-1]["id"], action="APPROVE"
        )
        cases.request_clarification(**self.common(), **self.pins(), text="توضيح مطلوب")
        with self.assertRaises(cases.CaseConflict):
            self.act("CLOSE")
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_close_without_delivery_requires_separate_grant_and_explicit_choice(self):
        self.approved()
        with self.assertRaisesMessage(cases.CaseConflict, "explicit_no_delivery"):
            self.act("CLOSE", without_delivery=False)
        self.authority.revoke("CLOSE_WITHOUT_DELIVERY")
        with self.assertRaisesMessage(cases.CaseConflict, "permission_denied"):
            self.act("CLOSE")
        self.assertFalse(self.read()["actions"])
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_action_grants_are_independent_and_archive_requires_closed(self):
        self.approved()
        with self.assertRaises(cases.CaseConflict):
            self.act("ARCHIVE")
        self.act("CLOSE")
        self.authority.revoke("ARCHIVE")
        with self.assertRaises(cases.CaseConflict):
            self.act("ARCHIVE")
        self.assertEqual([a["action"] for a in self.read()["actions"]], ["REOPEN"])
        self.act("REOPEN")
        self.assertEqual(LifecycleEvent.objects.count(), 2)

    def test_exact_command_retry_is_idempotent_and_changed_retry_conflicts(self):
        self.approved()
        command_id, pins = uuid.uuid4(), self.pins()
        first = self.act("CLOSE", command_id=command_id, expected_version=0, **pins)
        retry = self.act("CLOSE", command_id=command_id, expected_version=0, **pins)
        self.assertEqual(first["event_id"], retry["event_id"])
        self.assertTrue(retry["replayed"])
        with self.assertRaisesMessage(cases.CaseConflict, "command_conflict"):
            self.act("CLOSE", command_id=command_id, expected_version=0, reason="سبب مختلف", **pins)
        self.assertEqual(LifecycleEvent.objects.count(), 1)

    def test_stale_case_evidence_and_lifecycle_versions_do_not_write(self):
        self.approved()
        original = self.pins()
        self.act("CLOSE")
        for changes in (
            {"expected_version": 0},
            {"expected_revision": 1},
            {"expected_evidence_version": 99},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.act("REOPEN", **changes)
        self.followup()
        with self.assertRaises(cases.CaseConflict):
            self.act("CLOSE", **original)
        self.assertEqual(LifecycleEvent.objects.count(), 2)

    def test_concurrent_close_has_one_event_and_one_stale_conflict(self):
        self.approved()
        ready, pins = Barrier(2), self.pins()

        def attempt(actor):
            close_old_connections()
            try:
                ready.wait(timeout=5)
                try:
                    return services.command(
                        **self.common(actor=actor),
                        **pins,
                        action="CLOSE",
                        reason="إغلاق متزامن",
                        expected_version=0,
                        command_id=uuid.uuid4(),
                        without_delivery=True,
                    )["state"]
                except cases.CaseConflict:
                    return "CONFLICT"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(attempt, ["mufti-a", "mufti-b"]))
        self.assertCountEqual(result, ["CLOSED", "CONFLICT"])
        self.assertEqual(LifecycleEvent.objects.count(), 1)

    def test_requester_followup_reopens_same_closed_case_once(self):
        self.approved()
        self.act("CLOSE")
        result = self.followup()
        current = Case.objects.get(pk=self.receipt["case_id"])
        self.assertEqual(result["public_ref"], self.receipt["public_ref"])
        self.assertEqual(self.read()["state"], "OPEN")
        self.assertEqual(current.evidence_version, 2)
        self.assertEqual(current.stage, "UNDER_REVIEW")
        self.assertIsNone(current.approved_answer_id)
        with synthetic_queue_atomic():
            services.record_followup(case=current, event=current.events.latest("sequence"))
        self.assertEqual(LifecycleEvent.objects.count(), 2)
        self.assertEqual(LifecycleEvent.objects.latest("version").actor_kind, "REQUESTER_EVENT")
        self.assertEqual(current.answers.count(), 1)
        self.assertEqual(current.decisions.count(), 1)

    def test_archived_requester_followup_returns_to_regular_queue(self):
        self.approved()
        self.act("CLOSE")
        self.act("ARCHIVE")
        self.followup()
        rows = cases.list_cases(**{k: v for k, v in self.common().items() if k != "case_id"})
        with services.queue_projection(
            rows, **{k: v for k, v in self.common().items() if k != "case_id"}
        ) as visible:
            self.assertEqual(len(visible), 1)
            self.assertEqual(visible[0]["lifecycle"]["state"], "OPEN")
        self.assertEqual(LifecycleEvent.objects.latest("version").before_state, "ARCHIVED")

    def test_actual_attachment_followup_uses_same_canonical_reopen_contract(self):
        self.approved()
        self.act("CLOSE")
        self.act("ARCHIVE")
        with synthetic_queue_atomic():
            current = Case.objects.get(pk=self.receipt["case_id"])
            attachments.upload(
                token=self.receipt["token"],
                raw=b"synthetic new facts",
                filename="synthetic.txt",
                media_type="text/plain",
                expected_revision=current.revision,
                synthetic_fixtures_only=True,
            )
            current.refresh_from_db()
            services.record_followup(case=current, event=current.events.latest("sequence"))
        self.assertEqual(self.read()["state"], "OPEN")
        self.assertEqual(LifecycleEvent.objects.latest("version").evidence_version, 2)

    def test_invalid_or_foreign_canonical_event_cannot_reopen(self):
        self.approved()
        self.act("CLOSE")
        current = Case.objects.get(pk=self.receipt["case_id"])
        with self.assertRaises(cases.CaseConflict):
            services.record_followup(case=current, event=current.events.first())
        with synthetic_queue_atomic(), self.assertRaises(cases.CaseConflict):
            services.record_followup(case=current, event=current.events.latest("sequence"))
        self.assertEqual(LifecycleEvent.objects.count(), 1)

    def test_native_restore_keeps_case_closed_until_separate_reopen(self):
        self.approved()
        self.act("CLOSE")
        self.act("ARCHIVE")
        self.act("RESTORE")
        self.assertEqual(self.read()["state"], "CLOSED")
        self.assertIsNotNone(Case.objects.get(pk=self.receipt["case_id"]).approved_answer_id)

    def test_closed_case_requires_reopen_before_staff_work_but_access_is_independent(self):
        self.approved()
        self.act("CLOSE")
        current = Case.objects.get(pk=self.receipt["case_id"])
        for action in ("SAVE_ANSWER", "CLARIFICATION", "APPROVE", "RETURN_FOR_CHANGES"):
            with (
                synthetic_queue_atomic(),
                self.assertRaisesMessage(cases.CaseConflict, "reopen_before"),
            ):
                services.before_canonical_event(case=current, action=action)
        services.before_canonical_event(case=current, action="ROTATE_ACCESS")
        services.before_canonical_event(case=current, action="REVOKE_ACCESS")
        self.act("REOPEN")
        with synthetic_queue_atomic():
            services.before_canonical_event(case=current, action="SAVE_ANSWER")

    def test_missing_reopen_hook_after_disabled_feature_fails_closed_on_reenable(self):
        self.approved()
        self.act("CLOSE")
        with override_settings(FATWA_CASE_LIFECYCLE_ENABLED=False):
            cases.add_followup(
                token=self.receipt["token"],
                text="وقائع أثناء توقف الميزة",
                expected_revision=self.pins()["expected_revision"],
                synthetic_fixtures_only=True,
            )
        with self.assertRaisesMessage(cases.CaseConflict, "canonical_reopen_missing"):
            self.read()

    def test_value_equal_policy_replacement_and_flag_change_during_render_are_rejected(self):
        common = {key: value for key, value in self.common().items() if key != "case_id"}
        replacement = Authority(self.authority.refs, self.authority.provider_id)
        with services.projection_boundary(**common) as guard:
            with override_settings(FATWA_CASE_LIFECYCLE_AUTHORITY=replacement):
                with self.assertRaises(cases.CaseConflict):
                    guard.check()
            with override_settings(FATWA_CASE_LIFECYCLE_ENABLED=False):
                with self.assertRaises(cases.CaseConflict):
                    guard.check()

    def test_read_permission_filters_counts_before_query_and_state(self):
        other, foreign = self.intake("other"), self.intake("foreign")
        self.grant_all(other)
        self.authority.refs.add(other["public_ref"])
        self.approved()
        self.approved(other)
        self.act("CLOSE")
        self.act("CLOSE", receipt=other)
        self.act("ARCHIVE", receipt=other)
        common = {k: v for k, v in self.common().items() if k != "case_id"}
        self.authority.revoke("READ", other["public_ref"])
        result = services.inbox(**common, state="ALL")
        self.assertEqual(result["counts"], {"OPEN": 0, "CLOSED": 1, "ARCHIVED": 0})
        self.assertEqual(result["count"], 1)
        self.assertNotIn(other["public_ref"], str(result["rows"]))
        self.assertNotIn(foreign["public_ref"], str(result["rows"]))
        self.assertEqual(services.inbox(**common, state="ARCHIVED")["count"], 0)

    def test_normal_queue_excludes_closed_and_archived_before_counts(self):
        self.approved()
        common = {k: v for k, v in self.common().items() if k != "case_id"}
        for action in ("CLOSE", "ARCHIVE"):
            self.act(action)
            rows = cases.list_cases(**common)
            with services.queue_projection(rows, **common) as visible:
                self.assertEqual(visible, [])
        self.act("RESTORE")
        rows = cases.list_cases(**common)
        with services.queue_projection(rows, states=("CLOSED",), **common) as visible:
            self.assertEqual(len(visible), 1)

    def test_queue_rejects_stale_dtos_and_late_changes(self):
        self.approved()
        common = {k: v for k, v in self.common().items() if k != "case_id"}
        rows = cases.list_cases(**common)
        self.followup()
        with self.assertRaisesMessage(cases.CaseConflict, "queue_source_changed"):
            with services.queue_projection(rows, **common):
                pass
        self.approved()
        rows = cases.list_cases(**common)
        with self.assertRaises(cases.CaseConflict):
            with services.queue_projection(rows, **common):
                self.act("CLOSE")
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_scope_reduction_even_without_epoch_change_rejects_entire_batch(self):
        other = self.intake("other")
        self.grant_all(other)
        self.authority.refs.add(other["public_ref"])
        final = sorted([self.receipt, other], key=lambda r: r["case_id"])[-1]
        triggered = False

        def revoke(arguments):
            nonlocal triggered
            if not triggered and arguments["case_ref"] == final["public_ref"]:
                triggered = True
                actor = self.directory.identities["mufti-a"]
                self.directory.identities["mufti-a"] = replace(
                    actor, case_keys=frozenset({final["public_ref"]})
                )

        self.authority.callback = revoke
        with self.assertRaisesMessage(cases.CaseConflict, "identity_changed"):
            services.inbox(
                **{k: v for k, v in self.common().items() if k != "case_id"}, state="ALL"
            )

    def test_policy_change_during_final_callback_rejects_prior_permission(self):
        self.approved()
        self.act("CLOSE")
        calls = 0

        def revoke(arguments):
            nonlocal calls
            calls += 1
            if calls == 4:
                self.authority.revoke("READ")

        self.authority.callback = revoke
        with self.assertRaises(cases.CaseConflict):
            self.read()

    def test_read_baseline_precedes_callbacks_that_write_real_lifecycle_state(self):
        self.approved()
        changed = False

        def close(arguments):
            nonlocal changed
            if not changed and arguments["action"] == "READ":
                changed = True
                self.act("CLOSE")

        self.authority.callback = close
        with self.assertRaisesMessage(cases.CaseConflict, "projection_changed"):
            self.read()
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_identity_expiry_refresh_is_not_a_false_revocation(self):
        self.approved()
        with services.projection_boundary(
            **{k: v for k, v in self.common().items() if k != "case_id"}
        ) as guard:
            guard.permit(guard.locked[0], "READ")
            self.directory.identities["mufti-a"] = replace(
                self.directory.identities["mufti-a"],
                valid_until=timezone.now() + timedelta(minutes=40),
            )

    def test_database_rejects_history_mutation_delete_and_invalid_transition(self):
        self.approved()
        self.act("CLOSE")
        event = LifecycleEvent.objects.get()
        with self.assertRaises(DatabaseError), transaction.atomic():
            LifecycleEvent.objects.filter(pk=event.pk).update(reason="tampered")
        with self.assertRaises(DatabaseError), transaction.atomic():
            event.delete()
        event.pk, event.version, event.command_id = uuid.uuid4(), 2, uuid.uuid4()
        event.previous_sha256 = event.sha256
        event.sha256 = services._event_hash(event)
        with self.assertRaises(DatabaseError), transaction.atomic():
            event.save(force_insert=True)
        self.assertEqual(LifecycleEvent.objects.count(), 1)

    def test_database_rejects_cross_case_answer_and_stale_pins(self):
        self.approved()
        self.act("CLOSE")
        event = LifecycleEvent.objects.get()
        other = self.intake("other")
        self.grant_all(other)
        self.authority.refs.add(other["public_ref"])
        self.approved(other)
        event.pk, event.version, event.command_id = uuid.uuid4(), 2, uuid.uuid4()
        event.action, event.before_state, event.state = "REOPEN", "CLOSED", "OPEN"
        event.previous_sha256 = event.sha256
        event.answer_id = Case.objects.get(pk=other["case_id"]).approved_answer_id
        event.sha256 = services._event_hash(event)
        with self.assertRaises(DatabaseError), transaction.atomic():
            event.save(force_insert=True)
        event.answer_id = Case.objects.get(pk=self.receipt["case_id"]).approved_answer_id
        event.case_revision = 1
        event.sha256 = services._event_hash(event)
        with self.assertRaises(DatabaseError), transaction.atomic():
            event.save(force_insert=True)

    def test_populated_integrity_migration_reverse_reapply_preserves_history(self):
        self.approved()
        self.act("CLOSE")
        before = list(LifecycleEvent.objects.values())
        executor = MigrationExecutor(connection)
        executor.migrate([("case_lifecycle", "0001_initial")])
        try:
            MigrationExecutor(connection).migrate([("case_lifecycle", "0002_integrity")])
        finally:
            MigrationExecutor(connection).migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(list(LifecycleEvent.objects.values()), before)
        with self.assertRaises(DatabaseError), transaction.atomic():
            LifecycleEvent.objects.update(reason="tampered after restoration")


@override_settings(**FEATURES)
class LifecycleHTTPTests(Fixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.approved()
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        page = self.client.get("/casework/staff/login/")
        response = post(
            self.client,
            "/casework/staff/login/",
            {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "credential": self.directory.credentials["mufti-a"],
            },
            page,
        )
        self.assertEqual(response.status_code, 303)

    def send(self, action, page=None, **extra):
        page = page or self.client.get("/casework/staff/")
        fields = {"csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), "action": action}
        if action not in {"lc_inbox", "lc_filter"}:
            fields["case_ref"] = self.receipt["public_ref"]
        return post(self.client, "/casework/staff/", {**fields, **extra}, page)

    def form(self, page, action, **changes):
        values = {
            key: hidden(page, key)
            for key in ("revision", "evidence_version", "version", "command_id")
        }
        values.update(reason="سبب واضح من النموذج", confirm="yes")
        if action == "lc_close":
            values["without_delivery"] = "yes"
        return self.send(action, page, **{**values, **changes})

    def test_native_full_cycle_and_search_reset_defaults(self):
        page = self.send("lc_open")
        self.assertContains(page, "دورة حياة القضية")
        self.assertContains(page, 'data-state="OPEN"')
        for action, state in [
            ("lc_close", "CLOSED"),
            ("lc_archive", "ARCHIVED"),
            ("lc_restore", "CLOSED"),
            ("lc_reopen", "OPEN"),
        ]:
            page = self.form(page, action)
            self.assertContains(page, f'data-state="{state}"')
        self.assertContains(page, "إغلاق باختيار صريح دون ادعاء توصيل")
        page = self.send("lc_filter", state="ALL", query=self.receipt["public_ref"])
        self.assertContains(page, self.receipt["public_ref"])
        page = self.send("lc_inbox", page)
        self.assertContains(page, 'value="ARCHIVED" selected')
        self.assertContains(page, 'name="query" maxlength="128" value=""')

    def test_explicit_no_delivery_checkbox_cannot_be_omitted(self):
        page = self.send("lc_open")
        response = self.form(page, "lc_close", without_delivery="no")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_another_current_scoped_mufti_can_close_without_impersonating_approver(self):
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        page = self.client.get("/casework/staff/login/")
        result = post(
            self.client,
            "/casework/staff/login/",
            {"credential": self.directory.credentials["mufti-b"]},
            page,
        )
        self.assertEqual(result.status_code, 303)
        page = self.send("lc_open")
        self.assertContains(page, 'data-lifecycle-action="CLOSE"')
        result = self.form(page, "lc_close")
        self.assertContains(result, 'data-state="CLOSED"')
        self.assertEqual(LifecycleEvent.objects.get().subject_id, "mufti-b")
        self.assertEqual(
            Case.objects.get(pk=self.receipt["case_id"]).approved_answer.subject_id, "mufti-a"
        )

    def test_native_rejects_missing_confirmation_extra_fields_and_stale_version(self):
        page = self.send("lc_open")
        self.assertEqual(self.form(page, "lc_close", confirm="no").status_code, 400)
        self.assertEqual(self.form(page, "lc_close", role="MUFTI").status_code, 400)
        self.assertEqual(self.form(page, "lc_close", version="2").status_code, 409)
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_native_read_only_projection_rejects_real_withdrawal_during_render(self):
        original = views.render

        def render_then_change(*args, **kwargs):
            response = original(*args, **kwargs)
            self.act("CLOSE")
            return response

        with patch.object(views, "render", side_effect=render_then_change):
            response = self.send("lc_open")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(LifecycleEvent.objects.count(), 0)
        self.assertNotContains(response, self.receipt["public_ref"], status_code=409)

    def test_native_mutation_render_revoke_rolls_back_own_command(self):
        page = self.send("lc_open")
        original = views.render

        def revoke_during_render(*args, **kwargs):
            response = original(*args, **kwargs)
            self.authority.revoke("READ")
            return response

        with patch.object(views, "render", side_effect=revoke_during_render):
            response = self.form(page, "lc_close")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_reason_html_is_escaped_and_private_headers_retained(self):
        page = self.send("lc_open")
        response = self.form(page, "lc_close", reason="<script>bad()</script>")
        self.assertContains(response, "&lt;script&gt;bad()&lt;/script&gt;")
        self.assertNotContains(response, "<script>bad()</script>")
        self.assertIn("no-store", response["Cache-Control"])
