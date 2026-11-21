"""Current source lifecycle, source grants and human work survive regeneration."""

import tempfile
import uuid

from django.test import TransactionTestCase, override_settings

from apps.ai_gateway import services as gateway
from apps.ai_gateway.models import CandidateBatch
from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument
from apps.casework import services as cases
from apps.record_suppression import services as suppression
from apps.record_suppression.journal import LocalJournal
from apps.record_suppression.test_support import Authority as SuppressionAuthority

from .test_support import FEATURES, Fixture


@override_settings(**FEATURES)
class CurrentSourceTests(Fixture, TransactionTestCase):
    def test_withdrawn_library_source_is_never_regenerated_from_saved_ai_pins(self):
        self.change(kind="AI_CANDIDATES")
        self.decide(self.material, "WITHDRAW")
        with self.assertRaises(cases.CaseConflict):
            self.change("REBUILD", "AI_CANDIDATES")
        self.assertEqual(len(self.ai_provider.calls), 1)
        self.assertFalse(CandidateBatch.objects.exists())
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)

    def test_restoring_source_does_not_restore_a_cleared_search_or_ai_payload(self):
        self.change()
        self.change(kind="AI_CANDIDATES")
        with tempfile.TemporaryDirectory(prefix="derived-current-source-") as root:
            floor = LocalJournal(root=root, ledger_id=str(uuid.uuid4()))
            floor.initialize()
            authority = SuppressionAuthority(
                self.directory,
                [
                    ("CASE", self.receipt["case_id"]),
                    ("LIBRARY_VERSION", self.material["version_id"]),
                ],
                subjects=("editor",),
            )

            def change(kind, identifier, action):
                with suppression.inspect(kind=kind, identifier=identifier, **self.base) as current:
                    row = current["item"]
                    proposal = dict(
                        action=action,
                        kind=kind,
                        identifier=identifier,
                        source_digest=row["source_digest"],
                        head=row["head"],
                        watermark=current["watermark"],
                        reason="إجراء مصدر اصطناعي مستقل",
                        request_key=str(uuid.uuid4()),
                    )
                with suppression.preview(proposal=proposal, **self.base) as plan:
                    pass
                with suppression.apply(plan=plan, confirmed=True, **self.base):
                    pass

            with override_settings(
                FATWA_RECORD_SUPPRESSION_ENABLED=True,
                FATWA_RECORD_SUPPRESSION_JOURNAL=floor,
                FATWA_RECORD_SUPPRESSION_AUTHORITY=authority,
            ):
                change("CASE", self.receipt["case_id"], "SOFT_DELETE")
                with self.assertRaises(cases.CaseConflict):
                    self.change("REBUILD")
                change("CASE", self.receipt["case_id"], "RESTORE")
                change("LIBRARY_VERSION", self.material["version_id"], "SOFT_DELETE")
                with self.assertRaises(cases.CaseConflict):
                    self.change("REBUILD", "AI_CANDIDATES")
                change("LIBRARY_VERSION", self.material["version_id"], "RESTORE")
                self.assertFalse(SearchDocument.objects.exists())
                self.assertFalse(CandidateBatch.objects.exists())
                with self.assertRaises(cases.CaseConflict):
                    with gateway.read_boundary(**self.common, run_id=self.run["id"]):
                        pass
                self.change("REBUILD")
                fresh = self.change("REBUILD", "AI_CANDIDATES")
                self.assertNotEqual(fresh["child_id"], self.run["id"])
                self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)
                with gateway.read_boundary(**self.common, run_id=fresh["child_id"]) as current:
                    self.assertEqual(len(current["candidates"]), 1)

    def test_independent_read_cite_and_ai_grants_are_required_before_new_provider_call(self):
        self.change(kind="AI_CANDIDATES")
        for denied in ("READ", "CITE"):
            self.authority.denied.add(denied)
            with self.assertRaises(cases.CaseConflict):
                self.change("REBUILD", "AI_CANDIDATES")
            self.assertEqual(len(self.ai_provider.calls), 1)
            self.authority.denied.clear()
        self.assertEqual(self.change("REBUILD", "AI_CANDIDATES")["status"], "SUCCEEDED")
