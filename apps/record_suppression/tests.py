import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseSource
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic

from . import catalog, integration, services, store
from .models import SuppressionEvent
from .test_support import FEATURES, Fixture


@override_settings(**FEATURES)
class SuppressionTests(Fixture, TransactionTestCase):
    def test_one_empty_store_pin_still_rejects_new_policy_before_projection_returns(self):
        self.assertFalse(SuppressionEvent.objects.exists())
        with override_settings(
            FATWA_RECORD_SUPPRESSION_ENABLED=False, FATWA_RECORD_SUPPRESSION_JOURNAL=None
        ):
            with self.assertRaises(catalog.SuppressionDenied):
                with privacy.projection(atomic=False) as guard:
                    for kind, identifier in (
                        ("CASE", self.receipt["case_id"]),
                        ("ANSWER", self.answer_id),
                        ("CASE", self.receipt["case_id"]),
                    ):
                        integration.require(kind, identifier)
                    self.assertEqual(len(guard.retained_suppression), 1)
                    with override_settings(
                        FATWA_RECORD_SUPPRESSION_ENABLED=True,
                        FATWA_RECORD_SUPPRESSION_JOURNAL=self.journal,
                    ):
                        self.change()
                    # A second source admission must already see the new policy,
                    # before the retained final projection check runs.
                    with self.assertRaises(catalog.SuppressionDenied):
                        integration.require("CASE", self.receipt["case_id"])
        self.assertEqual(SuppressionEvent.objects.count(), 1)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        self.change("RESTORE")
        self.assertIn("أصل سؤال", self.read()["original_question"])

    def test_case_suppression_hides_current_reads_queue_followup_and_idempotent_intake(self):
        before = self.read()
        source = list(CaseSource.objects.values())
        result = self.change()
        self.assertEqual(result["state"], "SOFT_DELETED")
        for read in (
            self.read,
            lambda: cases.requester_status(self.receipt["token"], synthetic_fixtures_only=True),
            lambda: cases.intake_case(**self.intake),
            lambda: cases.add_followup(
                token=self.receipt["token"],
                text="لا يضاف",
                expected_revision=self.case.revision,
                synthetic_fixtures_only=True,
            ),
            lambda: cases.save_answer(
                case_id=str(self.case.pk),
                text="لا يضاف",
                expected_revision=self.case.revision,
                expected_evidence_version=self.case.evidence_version,
                **self.suppression_common("mufti"),
            ),
        ):
            with self.assertRaises(catalog.SuppressionDenied):
                read()
        self.assertEqual(cases.list_cases(**self.suppression_common("mufti")), [])
        self.assertEqual(list(CaseSource.objects.values()), source)
        self.assertEqual(Case.objects.get(pk=self.case.pk).stage, self.case.stage)
        self.change("RESTORE")
        self.assertEqual(self.read(), before)
        self.assertEqual(
            [row.state for row in SuppressionEvent.objects.order_by("sequence")],
            ["SOFT_DELETED", "RESTORED"],
        )
        self.assertEqual(SuppressionEvent.objects.first().role, "ORGANIZER_ADMIN")

    def test_answer_target_is_exact_and_never_approved_after_suppression(self):
        self.change(kind="ANSWER", identifier=self.answer_id)
        self.assertEqual(self.read()["answers"], [])
        self.assertIn("أصل سؤال", self.read()["original_question"])
        with self.assertRaises(catalog.SuppressionDenied):
            cases.record_decision(
                case_id=str(self.case.pk),
                answer_id=self.answer_id,
                action="APPROVE",
                expected_revision=self.case.revision,
                expected_evidence_version=self.case.evidence_version,
                **self.suppression_common("mufti"),
            )
        self.change("RESTORE", kind="ANSWER", identifier=self.answer_id)
        self.assertEqual(len(self.read()["answers"]), 1)

    def test_no_role_default_or_operational_impersonation_or_scope_expansion(self):
        self.suppression_authority.revoke("SOFT_DELETE", subject="mufti")
        with self.assertRaises(catalog.SuppressionDenied):
            self.plan(subject="mufti")
        with self.assertRaises(catalog.SuppressionDenied):
            with services.desk(**self.suppression_common("operator")):
                pass
        self.directory.identities["admin"] = replace(
            self.directory.identities["admin"], case_keys=frozenset({"unscoped-other-case"})
        )
        with self.assertRaises(catalog.SuppressionDenied):
            self.plan()
        self.assertEqual(SuppressionEvent.objects.count(), 0)

    def test_exact_preview_cas_and_replay_do_not_append_again(self):
        old, other = self.plan(), self.plan()
        with services.apply(plan=old, confirmed=True, **self.suppression_common()):
            pass
        for value in (old, other):
            with self.assertRaises(catalog.SuppressionDenied):
                with services.apply(plan=value, confirmed=True, **self.suppression_common()):
                    pass
        self.assertEqual(SuppressionEvent.objects.count(), 1)
        self.assertEqual(len(self.journal.snapshot()), 1)

    def test_concurrent_confirmations_have_one_sql_and_journal_winner(self):
        plans = [self.plan(), self.plan()]
        ready = Barrier(2)

        def apply(plan):
            close_old_connections()
            try:
                ready.wait(timeout=5)
                try:
                    with services.apply(
                        plan=plan, confirmed=True, **self.suppression_common()
                    ) as result:
                        return result["state"]
                except catalog.SuppressionDenied:
                    return "CONFLICT"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, plans))
        self.assertCountEqual(results, ["SOFT_DELETED", "CONFLICT"])
        self.assertEqual(SuppressionEvent.objects.count(), 1)
        self.assertEqual(len(self.journal.snapshot()), 1)

    def test_late_render_or_last_callback_cannot_return_an_old_material_projection(self):
        with self.assertRaises(catalog.SuppressionDenied):
            with privacy.projection():
                self.read()
                self.change()
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        self.change("RESTORE")
        self.assertEqual(len(self.read()["answers"]), 1)

    def test_disabled_missing_omitted_app_and_stale_journal_fail_closed(self):
        empty = Path(self.journal.root / "decisions.json").read_bytes()
        self.change()
        current = Path(self.journal.root / "decisions.json").read_bytes()
        for values in (
            {"FATWA_RECORD_SUPPRESSION_ENABLED": False},
            {"FATWA_RECORD_SUPPRESSION_JOURNAL": None},
        ):
            with override_settings(**values), self.assertRaises(catalog.SuppressionDenied):
                self.read()
        from django.conf import settings

        with (
            override_settings(
                INSTALLED_APPS=[
                    x for x in settings.INSTALLED_APPS if x != "apps.record_suppression"
                ]
            ),
            self.assertRaises(catalog.SuppressionDenied),
        ):
            self.read()
        Path(self.journal.root / "decisions.json").write_bytes(empty)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        Path(self.journal.root / "decisions.json").write_bytes(current)
        self.change("RESTORE")
        self.assertTrue(self.read())

    def test_external_floor_contains_no_original_reason_or_access_secret(self):
        plan = self.plan()
        plan["proposal"]["reason"] = "سبب داخلي لا ينسخ للدفتر الخارجي"
        # The plan is service checked afresh, not a free grant; the browser also seals it.
        with services.preview(proposal=plan["proposal"], **self.suppression_common()) as approved:
            saved_plan = approved
        with services.apply(plan=saved_plan, confirmed=True, **self.suppression_common()):
            pass
        raw = Path(self.journal.root / "decisions.json").read_text()
        for value in (
            self.intake["original_question"],
            plan["proposal"]["reason"],
            self.receipt["token"],
            "جواب محفوظ",
        ):
            self.assertNotIn(value, raw)
        self.assertIn("reason_sha256", raw)
        self.assertEqual(SuppressionEvent.objects.first().reason, plan["proposal"]["reason"])

    def test_newer_external_floor_requires_explicit_audited_reconciliation(self):
        plan = self.plan()
        with self.assertRaisesRegex(RuntimeError, "old snapshot"):
            with synthetic_queue_atomic(), transaction.atomic():
                with services.apply(plan=plan, confirmed=True, **self.suppression_common()):
                    pass
                raise RuntimeError("old snapshot")
        self.assertEqual(SuppressionEvent.objects.count(), 0)
        self.assertEqual(len(self.journal.snapshot()), 1)
        with self.assertRaisesRegex(catalog.SuppressionDenied, "reconciliation_required"):
            self.read()
        saved_grants = set(self.suppression_authority.grants)
        self.suppression_authority.revoke("RECONCILE")
        with self.assertRaises(catalog.SuppressionDenied):
            self.plan("RECONCILE")
        self.suppression_authority.grants = saved_grants
        self.change("RECONCILE")
        row = SuppressionEvent.objects.get()
        self.assertTrue(row.recovered)
        self.assertEqual(row.applied_subject_id, "admin")
        self.assertEqual(row.reason, "")
        self.assertTrue(row.recovery_reason)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        self.change("RESTORE")
        self.assertTrue(self.read())

    def test_reconciliation_is_bounded_and_stays_closed_between_batches(self):
        self.change()
        events = self.journal.snapshot()
        for sequence in range(2, 131):
            previous = events[-1]
            restoring = previous["state"] == "SOFT_DELETED"
            value = {
                **previous,
                "id": str(uuid.uuid4()),
                "sequence": sequence,
                "version": sequence,
                "previous_digest": catalog.digest(previous),
                "previous_state": previous["state"],
                "action": "RESTORE" if restoring else "SOFT_DELETE",
                "state": "RESTORED" if restoring else "SOFT_DELETED",
            }
            events = self.journal.append(events, value)
        self.assertEqual(SuppressionEvent.objects.count(), 1)
        first = self.plan("RECONCILE")
        self.assertEqual(len(first["resources"]), services.RECONCILE_BATCH)
        self.assertLess(len(catalog.canonical(first)), 200000)
        with services.apply(plan=first, confirmed=True, **self.suppression_common()) as result:
            self.assertTrue(result["still_closed"])
            self.assertEqual(result["count"], 128)
        self.assertEqual(SuppressionEvent.objects.count(), 129)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        last = self.change("RECONCILE")
        self.assertFalse(last["still_closed"])
        self.assertEqual(last["count"], 1)
        self.assertEqual(SuppressionEvent.objects.count(), 130)
        self.assertEqual(len(self.read()["answers"]), 1)

    def test_invalid_reason_is_rejected_before_any_external_floor_append(self):
        proposal = self.proposal()
        for note in ("invalid\x00reason", "invalid\ud800reason"):
            with self.assertRaises(catalog.SuppressionDenied):
                with services.preview(
                    proposal={**proposal, "reason": note}, **self.suppression_common()
                ):
                    pass
        self.assertEqual(self.journal.snapshot(), [])
        self.assertEqual(SuppressionEvent.objects.count(), 0)
        self.assertTrue(self.read())

    def test_late_authority_revoke_after_append_rolls_sql_back_but_not_the_safe_floor(self):
        plan = self.plan()

        def late(values):
            if self.journal.snapshot():
                self.suppression_authority.revoke("SOFT_DELETE")

        self.suppression_authority.hook = late
        with self.assertRaises(catalog.SuppressionDenied):
            with services.apply(plan=plan, confirmed=True, **self.suppression_common()):
                pass
        self.suppression_authority.hook = None
        self.assertEqual(SuppressionEvent.objects.count(), 0)
        self.assertEqual(len(self.journal.snapshot()), 1)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        self.change("RECONCILE")
        self.change("RESTORE")
        self.assertTrue(self.read())

    def test_sql_immutable_chain_seal_and_populated_reversal(self):
        self.change()
        row = SuppressionEvent.objects.get()
        for operation in (
            lambda: SuppressionEvent.objects.filter(pk=row.pk).update(reason="تبديل"),
            lambda: SuppressionEvent.objects.filter(pk=row.pk).delete(),
        ):
            with self.assertRaises(DatabaseError), synthetic_queue_atomic(), transaction.atomic():
                operation()
        value = self.journal.snapshot()[0]
        bad = {
            **value,
            "id": str(uuid.uuid4()),
            "sequence": 2,
            "version": 2,
            "previous_digest": row.digest,
        }
        with self.assertRaises(DatabaseError), synthetic_queue_atomic(), transaction.atomic():
            store.insert(
                bad,
                actor=self.directory.resolve("admin"),
                provider_id=self.directory.provider_id,
                reason=row.reason,
            )
        import importlib

        migration = importlib.import_module("apps.record_suppression.migrations.0002_integrity")
        with self.assertRaisesRegex(RuntimeError, "cannot_be_removed"):
            migration.reverse(None, type("Schema", (), {"connection": connection})())
        self.assertEqual(SuppressionEvent.objects.get().digest, row.digest)

    def test_journal_tamper_null_and_missing_file_are_explicit_denials(self):
        self.change()
        filename = self.journal.root / "decisions.json"
        original = filename.read_bytes()
        value = json.loads(original)
        value["events"][0]["role"] = None
        filename.write_text(catalog.canonical(value))
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        filename.write_bytes(original)
        with (
            patch.object(
                self.journal,
                "_open",
                side_effect=catalog.SuppressionDenied("suppression_journal_missing_or_unsafe"),
            ),
            self.assertRaises(catalog.SuppressionDenied),
        ):
            self.read()
        self.change("RESTORE")
        self.assertTrue(self.read())
