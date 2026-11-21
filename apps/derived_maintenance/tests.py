"""Real PostgreSQL payload removal, fresh regeneration and current recovery vetoes."""

import uuid

from django.apps import apps
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase, override_settings

from apps.ai_gateway import services as gateway
from apps.ai_gateway.models import CandidateBatch, GatewayOutcome, GatewayRun
from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument, SearchGeneration
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic

from . import services
from .models import DerivativeClear, DerivativeRebuild
from .test_support import FEATURES, Fixture


@override_settings(**FEATURES)
class DerivedMaintenanceTests(Fixture, TransactionTestCase):
    def preserved(self):
        owners = {
            "casework",
            "research_library",
            "precise_citations",
            "case_organization",
            "scholarly_links",
            "public_answer_media",
            "public_collections",
            "classification_review",
        }
        return {
            model._meta.label: list(model.objects.order_by("pk").values())
            for model in apps.get_models()
            if model._meta.app_label in owners
        }

    def test_clear_search_payload_keeps_headers_and_originals_and_blocks_old_open(self):
        original = self.preserved()
        found = search.search(**self.common, value="اصطناعي", mode="FTS")
        self.assertGreater(found["total"], 0)
        old = found["results"][0]
        count = SearchDocument.objects.count()
        result = self.change()
        self.assertEqual(result["count"], count)
        self.assertEqual(SearchDocument.objects.count(), 0)
        self.assertEqual(SearchGeneration.objects.count(), 1)
        self.assertEqual(search.desk(**self.common)["state"], "CLEARED")
        self.assertEqual(search.search(**self.common, value="اصطناعي")["total"], 0)
        with self.assertRaises(cases.CaseConflict):
            search.open_source(
                **self.common, generation_id=old["generation_id"], document_id=old["document_id"]
            )
        self.assertEqual(self.preserved(), original)
        row = DerivativeClear.objects.get()
        self.assertEqual(row.kind, "SEARCH_INDEX")
        self.assertNotIn("original_text", row.canonical_payload)

    def test_fresh_search_rebuild_preserves_reviewed_human_citations_and_approval(self):
        citation = self.save_citations()
        self.review_citations(citation)
        case = cases.Case.objects.get(pk=self.receipt["case_id"])
        cases.record_decision(
            **self.common,
            answer_id=citation["answer_id"],
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            action="APPROVE",
            note="اعتماد بشري اصطناعي",
        )
        original = self.preserved()
        self.change()
        result = self.change("REBUILD")
        self.assertNotEqual(result["child_id"], self.built["generation_id"])
        self.assertFalse(
            SearchDocument.objects.filter(generation_id=self.built["generation_id"]).exists()
        )
        self.assertGreater(
            SearchDocument.objects.filter(generation_id=result["child_id"]).count(), 0
        )
        self.assertEqual(search.desk(**self.common)["state"], "CURRENT")
        self.assertEqual(search.search(**self.common, value="عبارة", kind="ANSWER")["total"], 1)
        self.assertEqual(self.preserved(), original)
        self.assertEqual(DerivativeRebuild.objects.get().child_id, uuid.UUID(result["child_id"]))

    def test_ai_clear_and_new_request_use_gateway_and_leave_old_run_unusable(self):
        original = self.preserved()
        before = list(GatewayRun.objects.values()), list(GatewayOutcome.objects.values())
        self.change(kind="AI_CANDIDATES")
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(
            (list(GatewayRun.objects.values()), list(GatewayOutcome.objects.values())), before
        )
        with self.assertRaises(cases.CaseConflict):
            with gateway.read_boundary(**self.common, run_id=self.run["id"]):
                pass
        result = self.change("REBUILD", "AI_CANDIDATES")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertNotEqual(result["child_id"], self.run["id"])
        self.assertEqual(len(self.ai_provider.calls), 2)
        self.assertFalse(CandidateBatch.objects.filter(run_id=self.run["id"]).exists())
        with gateway.read_boundary(**self.common, run_id=result["child_id"]) as value:
            self.assertEqual(len(value["candidates"]), 1)
        self.assertEqual(self.preserved(), original)
        self.assertEqual(DerivativeRebuild.objects.get().status, "SUCCEEDED")

    def test_permissions_roles_source_processing_and_fresh_fragment_are_independent(self):
        self.maintenance_authority.denied.add(("editor", "CLEAR"))
        with self.assertRaises(cases.CaseConflict):
            self.plan()
        self.maintenance_authority.denied.clear()
        for subject in ("operator", "other"):
            with self.assertRaises(cases.CaseConflict):
                with services.desk(**{**self.base, "subject_id": subject}):
                    pass
        self.change(kind="AI_CANDIDATES")
        with self.assertRaises(cases.CaseConflict):
            self.plan("REBUILD", "AI_CANDIDATES", parameters={"query": "نص مختلف"})
        self.gateway_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY"))
        with self.assertRaises(cases.CaseConflict):
            self.change("REBUILD", "AI_CANDIDATES")
        self.assertEqual(len(self.ai_provider.calls), 1)
        self.gateway_authority.denied.clear()
        self.assertEqual(self.change("REBUILD", "AI_CANDIDATES")["status"], "SUCCEEDED")

    def test_admin_can_clear_with_exact_mandate_but_never_impersonates_mufti_to_rebuild(self):
        with services.preview(
            proposal=self.proposal(), **{**self.base, "subject_id": "admin"}
        ) as plan:
            pass
        with services.apply(plan=plan, confirmed=True, **{**self.base, "subject_id": "admin"}):
            pass
        self.assertEqual(DerivativeClear.objects.get().role, "ORGANIZER_ADMIN")
        with self.assertRaises(cases.CaseConflict):
            with services.preview(
                proposal=self.proposal("REBUILD"), **{**self.base, "subject_id": "admin"}
            ):
                pass

    def test_old_sql_and_new_external_clearance_require_audited_reconciliation(self):
        plan = self.plan()

        class RestoreOlderSQL(Exception):
            pass

        try:
            with synthetic_queue_atomic(), transaction.atomic():
                with services.apply(plan=plan, confirmed=True, **self.base):
                    pass
                raise RestoreOlderSQL
        except RestoreOlderSQL:
            pass
        self.assertEqual(DerivativeClear.objects.count(), 0)
        self.assertEqual(len(self.journal.snapshot()), 1)
        self.assertGreater(SearchDocument.objects.count(), 0)
        with self.assertRaises(cases.CaseConflict):
            search.search(**self.common, value="اصطناعي")
        self.assertEqual(self.change("RECONCILE")["count"], 1)
        self.assertTrue(DerivativeClear.objects.get().recovered)
        self.assertEqual(SearchDocument.objects.count(), 0)
        self.assertEqual(search.desk(**self.common)["state"], "CLEARED")
        self.change("REBUILD")
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)

    def test_source_or_management_revocation_during_provider_discards_new_output(self):
        self.change(kind="AI_CANDIDATES")
        self.ai_provider.hook = lambda: self.maintenance_authority.denied.add(("editor", "REBUILD"))
        with self.assertRaises(cases.CaseConflict):
            self.change("REBUILD", "AI_CANDIDATES")
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(DerivativeRebuild.objects.count(), 0)
        self.assertEqual(GatewayOutcome.objects.filter(status="REVOKED").count(), 1)
        self.ai_provider.hook = None
        self.maintenance_authority.denied.clear()
        self.assertEqual(self.change("REBUILD", "AI_CANDIDATES")["status"], "SUCCEEDED")

    def test_sql_rejects_unadmitted_deletion_and_clearance_history_mutation(self):
        for model in (SearchDocument, SearchGeneration, CandidateBatch, GatewayRun, GatewayOutcome):
            with self.assertRaises(DatabaseError), synthetic_queue_atomic(), transaction.atomic():
                model.objects.all().delete()
        old = CandidateBatch.objects.get()
        old.pk = uuid.uuid4()
        self.change(kind="AI_CANDIDATES")
        from apps.precise_citations.boundary import seal

        with self.assertRaises(DatabaseError), synthetic_queue_atomic(), transaction.atomic():
            seal(old)
        with self.assertRaises(DatabaseError), synthetic_queue_atomic(), transaction.atomic():
            DerivativeClear.objects.all().update(reason="تمويه")
        with self.assertRaises(DatabaseError), synthetic_queue_atomic(), transaction.atomic():
            DerivativeClear.objects.all().delete()

    def test_current_floor_and_default_off_do_not_reactivate_deleted_payload(self):
        self.change()
        for setting, value in (
            ("FATWA_DERIVED_MAINTENANCE_ENABLED", False),
            ("FATWA_DERIVED_MAINTENANCE_JOURNAL", None),
        ):
            with override_settings(**{setting: value}), self.assertRaises(cases.CaseConflict):
                search.search(**self.common, value="اصطناعي")
        root = self.journal.root / "decisions.json"
        saved = root.read_bytes()
        root.unlink()
        with self.assertRaises(cases.CaseConflict):
            search.search(**self.common, value="اصطناعي")
        root.write_bytes(saved)
        root.chmod(0o600)
        self.assertEqual(search.desk(**self.common)["state"], "CLEARED")

    def test_missing_provider_is_an_explicit_outcome_and_text_search_stays_usable(self):
        self.change(kind="AI_CANDIDATES")
        with override_settings(FATWA_AI_CITATION_PROVIDER=None):
            result = self.change("REBUILD", "AI_CANDIDATES")
        self.assertEqual(result["status"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(len(self.ai_provider.calls), 1)
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)
        self.assertEqual(DerivativeRebuild.objects.get().status, "PROVIDER_UNAVAILABLE")
