"""Direct SQL, concurrent commands and exact current journal contracts."""

import copy
import threading
import uuid
from unittest.mock import patch

from django.db import DatabaseError, close_old_connections, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument, SearchGeneration
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic

from . import catalog, journal, services, store
from .models import DerivativeClear
from .test_support import FEATURES, Fixture


@override_settings(**FEATURES)
class DerivedIntegrityTests(Fixture, TransactionTestCase):
    def value(self):
        target = catalog.target("SEARCH_INDEX", self.built["generation_id"])
        return dict(
            id=str(uuid.uuid4()),
            ledger_id=self.journal.ledger_id,
            sequence=1,
            previous_digest=catalog.ZERO,
            kind=target.kind,
            target_id=target.identifier,
            header_digest=target.header_digest,
            case_id=target.case_id,
            payload=target.manifest(),
            provider_id=self.directory.provider_id,
            subject_id="editor",
            role="MUFTI",
            auth_epoch="epoch-1",
            reason_sha256=catalog.text_hash("حذف مشتق اصطناعي"),
            occurred_at=catalog.stamp(timezone.now()),
        )

    def insert_direct(self, value):
        return DerivativeClear.objects.create(
            **{**value, "occurred_at": catalog.parse_stamp(value["occurred_at"])},
            canonical_payload=catalog.canonical(value),
            digest=catalog.digest(value),
            reason="حذف مشتق اصطناعي",
            applied_provider_id=self.directory.provider_id,
            applied_subject_id="editor",
            applied_role="MUFTI",
            applied_auth_epoch="epoch-1",
        )

    def test_sql_rejects_signed_json_null_or_unexpected_payload_keys(self):
        original = self.value()
        for key in ("id", "digest"):
            value = copy.deepcopy(original)
            value["payload"][0][key] = None
            with (
                self.assertRaisesMessage(DatabaseError, "derived_payload_manifest_invalid"),
                synthetic_queue_atomic(),
                transaction.atomic(),
            ):
                self.insert_direct(value)
        value = copy.deepcopy(original)
        value["payload"][0]["original_text"] = "لا يسمح بمتن داخل السجل"
        with (
            self.assertRaisesMessage(DatabaseError, "derived_payload_manifest_invalid"),
            synthetic_queue_atomic(),
            transaction.atomic(),
        ):
            self.insert_direct(value)
        self.assertEqual(DerivativeClear.objects.count(), 0)
        self.assertGreater(SearchDocument.objects.count(), 0)

    def test_sql_clearance_cannot_target_a_different_header_or_payload(self):
        for changed in (
            {"header_digest": "0" * 64},
            {"case_id": str(uuid.uuid4())},
            {"payload": [{"id": str(uuid.uuid4()), "digest": "0" * 64}]},
        ):
            value = {**self.value(), **changed}
            with (
                self.assertRaisesMessage(DatabaseError, "derived_exact_payload_required"),
                synthetic_queue_atomic(),
                transaction.atomic(),
            ):
                self.insert_direct(value)
        self.assertEqual(DerivativeClear.objects.count(), 0)

    def test_two_actual_concurrent_confirmations_have_one_clearance_and_no_payload(self):
        plan, barrier, outcomes = self.plan(), threading.Barrier(2), []

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with services.apply(plan=plan, confirmed=True, **self.base):
                    pass
                outcomes.append("APPLIED")
            except cases.CaseConflict:
                outcomes.append("REFUSED")
            except Exception as exc:
                outcomes.append(type(exc).__name__ + ":" + str(exc))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ["APPLIED", "REFUSED"])
        self.assertEqual(DerivativeClear.objects.count(), 1)
        self.assertEqual(len(self.journal.snapshot()), 1)
        self.assertEqual(SearchDocument.objects.count(), 0)

    def test_replay_of_the_original_search_request_cannot_restore_cleared_data(self):
        prior = SearchGeneration.objects.get(pk=self.built["generation_id"])
        self.change()
        with self.assertRaisesMessage(cases.CaseConflict, "search_request_cleared"):
            search.rebuild(
                **self.common,
                expected_revision=prior.case_revision,
                expected_evidence_version=prior.evidence_version,
                expected_generation=0,
                request_key=prior.request_key,
            )
        self.assertEqual(SearchDocument.objects.count(), 0)

    def test_journal_is_metadata_only_and_387_format_still_rejects_its_payload(self):
        self.change()
        content = (self.journal.root / "decisions.json").read_text()
        self.assertNotIn(self.source_text, content)
        self.assertNotIn("إجراء اصطناعي صريح", content)
        self.assertNotIn("original_text", content)
        self.assertEqual((self.journal.root / "decisions.json").stat().st_mode & 0o777, 0o600)
        from apps.record_suppression.journal import LocalJournal

        with self.assertRaises(cases.CaseConflict):
            LocalJournal(root=self.journal.root, ledger_id=self.journal.ledger_id).snapshot()

    def test_journal_bound_refuses_before_replacing_the_current_floor(self):
        path = self.journal.root / "decisions.json"
        before = path.read_bytes()
        with patch.object(journal, "MAX_BYTES", len(before) + 1):
            with self.assertRaisesMessage(cases.CaseConflict, "derived_journal_bound"):
                self.change()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.journal.snapshot(), [])
        self.assertEqual(DerivativeClear.objects.count(), 0)
        self.assertGreater(SearchDocument.objects.count(), 0)
        self.assertEqual(self.change()["action"], "CLEAR")

    def test_omitting_app_with_saved_clearances_never_enables_a_cleared_index(self):
        self.change()
        from django.conf import settings

        without = [name for name in settings.INSTALLED_APPS if name != "apps.derived_maintenance"]
        with override_settings(INSTALLED_APPS=without), self.assertRaises(cases.CaseConflict):
            search.search(**self.common, value="اصطناعي")

    def test_no_free_form_owner_or_source_deletion_is_available(self):
        for kind in (
            "CASE",
            "ANSWER",
            "RECORDING_TRANSCRIPT",
            "LIBRARY_VERSION",
            "all",
            "AI_EMBEDDING",
        ):
            with self.assertRaises(cases.CaseConflict):
                catalog.target(kind, self.receipt["case_id"])
        self.assertEqual(store.rows(), [])
