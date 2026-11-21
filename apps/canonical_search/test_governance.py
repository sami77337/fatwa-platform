"""Real SQL expansion, immutable human review, live shadow and late revocation."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import CaseEvent, CaseSource

from . import governance, services
from .governance_test_support import ENTRIES, FEATURES, TERM, GovernanceFixture
from .models import ShadowComparison, SynonymDecision, SynonymPreview, SynonymRevision


@override_settings(**FEATURES)
class SearchGovernanceTests(GovernanceFixture, TransactionTestCase):
    def test_reviewed_dictionary_changes_real_fts_only_with_exact_provenance(self):
        before = CaseEvent.objects.count()
        revision = self.revision()
        with self.assertRaises(cases.CaseConflict):
            governance.search(**self.common, revision_id=revision["id"], value=TERM)
        preview = self.preview(revision)
        self.assertEqual(preview["impact"][0]["baseline"]["total"], 0)
        self.assertEqual(preview["impact"][0]["candidate"]["total"], 2)
        with self.assertRaises(cases.CaseConflict):
            self.decide(revision, preview, subject_id="editor")
        # PostgreSQL JSON timestamps trim fractional zeros; compare their value,
        # while retaining the exact Python canonical bytes and immutable hash.
        with patch(
            "django.utils.timezone.now", return_value=timezone.now().replace(microsecond=120000)
        ):
            reviewed = self.decide(revision, preview)
        with CaptureQueriesContext(connection) as captured:
            result = governance.search(**self.common, revision_id=revision["id"], value=TERM)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["query"], TERM)
        self.assertEqual(
            result["expanded_terms"], [{"typed_token": TERM, "alternatives": ["المعاملات"]}]
        )
        self.assertEqual(result["dictionary"]["digest"], revision["digest"])
        self.assertEqual(result["dictionary"]["provenance"], revision["provenance"])
        self.assertEqual(result["dictionary"]["reviewer"], reviewed["reviewer"])
        sql = "\n".join(item["sql"] for item in captured)
        self.assertIn("@@", sql)
        self.assertIn("||", sql)
        self.assertEqual(services.search(**self.common, value=TERM, mode="FTS")["total"], 0)
        self.assertEqual(services.search(**self.common, value=TERM, mode="LITERAL")["total"], 0)
        self.assertEqual(CaseSource.objects.get().original_question, self.question)
        self.assertEqual(CaseEvent.objects.count(), before)

    def test_lineage_mapping_retirement_and_stale_version_keep_every_original(self):
        first, preview = self.approved()
        changed = [{"key": "synthetic-renamed", "term": "بديلمصطنع", "alternatives": ["الزكاة"]}]
        with self.assertRaises(cases.CaseConflict):
            self.revision(entries=changed, mapping=[])
        second = self.revision(
            entries=changed,
            mapping=[
                {
                    "from": ENTRIES[0]["key"],
                    "kind": "RENAMED",
                    "to": ["synthetic-renamed"],
                    "reason": "تسمية اختبارية جديدة مع احتفاظ الإصدار السابق",
                }
            ],
        )
        self.assertEqual(second["previous_id"], first["id"])
        self.assertEqual(second["state"], "DRAFT")
        with self.assertRaises(cases.CaseConflict):
            governance.search(**self.common, revision_id=second["id"], value="بديلمصطنع")
        self.assertEqual(
            governance.search(**self.common, revision_id=first["id"], value=TERM)["total"], 2
        )
        with self.assertRaises(cases.CaseConflict):
            self.revision(expected_number=1)
        self.decide(first, action="RETIRE", ttl_minutes=0)
        with self.assertRaises(cases.CaseConflict):
            governance.search(**self.common, revision_id=first["id"], value=TERM)
        self.assertEqual(SynonymRevision.objects.get(pk=first["id"]).entries, ENTRIES)
        self.assertEqual(SynonymPreview.objects.get(pk=preview["id"]).queries[0], TERM)
        self.assertEqual(SynonymDecision.objects.count(), 2)

    def test_split_merge_and_no_equivalent_are_explicit_mapping_not_history_edits(self):
        first = self.revision()
        split_entries = [
            {"key": "split-a", "term": "مصطنعأول", "alternatives": ["المعاملات"]},
            {"key": "split-b", "term": "مصطنعثان", "alternatives": ["الزكاة"]},
        ]
        split = self.revision(
            entries=split_entries,
            mapping=[
                {
                    "from": ENTRIES[0]["key"],
                    "kind": "SPLIT",
                    "to": ["split-a", "split-b"],
                    "reason": "تقسيم تجريبي صريح",
                }
            ],
        )
        merged_entries = [
            {"key": "merged-a", "term": "مصطنعمجموع", "alternatives": ["المعاملات", "الزكاة"]}
        ]
        merged = self.revision(
            entries=merged_entries,
            mapping=[
                {
                    "from": row["key"],
                    "kind": "MERGED",
                    "to": ["merged-a"],
                    "reason": "دمج تجريبي صريح",
                }
                for row in split_entries
            ],
        )
        self.revision(
            entries=[{"key": "replacement", "term": "مصطنعجديد", "alternatives": ["سؤال"]}],
            mapping=[
                {
                    "from": "merged-a",
                    "kind": "NO_EQUIVALENT",
                    "to": [],
                    "reason": "لا مقابل في النسخة التجريبية",
                }
            ],
        )
        self.assertEqual(
            [row.number for row in SynonymRevision.objects.order_by("number")], [1, 2, 3, 4]
        )
        self.assertEqual(
            SynonymRevision.objects.get(pk=split["id"]).previous_id.hex, uuid.UUID(first["id"]).hex
        )
        self.assertEqual(SynonymRevision.objects.get(pk=merged["id"]).entries, merged_entries)

    def test_live_shadow_executes_candidate_but_returns_identical_baseline_and_pins(self):
        revision, _ = self.approved()
        before = services.search(**self.common, value=TERM, mode="FTS")
        events = CaseEvent.objects.count()
        result = self.shadow(revision)
        self.assertEqual(result["result"], before)
        comparison = result["comparison"]
        self.assertEqual(comparison["baseline"]["total"], 0)
        self.assertEqual(comparison["candidate"]["total"], 2)
        self.assertEqual(len(comparison["difference"]["added"]), 2)
        self.assertTrue(comparison["baseline_retained"])
        self.assertFalse(comparison["promotion_performed"])
        self.assertEqual(comparison["dictionary_digest"], revision["digest"])
        for row in comparison["candidate"]["rows"]:
            opened = services.open_source(
                **self.common, generation_id=row["generation_id"], document_id=row["document_id"]
            )
            self.assertEqual(opened["pin"], row["pin"])
        self.assertEqual(CaseEvent.objects.count(), events)
        self.assertEqual(services.search(**self.common, value=TERM)["total"], 0)

    def test_real_candidate_sql_error_keeps_baseline_and_durable_explicit_failure(self):
        revision, _ = self.approved()
        baseline = services.search(**self.common, value="المعاملات")

        def database_failure(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1/0")

        with patch.object(governance, "_candidate", side_effect=database_failure):
            result = self.shadow(revision, value="المعاملات")
        self.assertEqual(result["result"], baseline)
        self.assertEqual(result["comparison"]["candidate_status"], "ERROR")
        self.assertEqual(result["comparison"]["candidate"], {})
        self.assertEqual(ShadowComparison.objects.count(), 1)
        self.assertEqual(
            governance.read_shadow(**self.common, comparison_id=result["comparison"]["id"])[
                "candidate_status"
            ],
            "ERROR",
        )

    def test_same_request_replays_without_extra_rows_and_concurrent_plan_is_serialized(self):
        key = uuid.uuid4()

        def create():
            close_old_connections()
            try:
                return self.revision(expected_number=0, request_key=key)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(SynonymRevision.objects.count(), 1)
        revision = results[0]
        preview = self.preview(revision)
        self.decide(revision, preview)
        shadow_key = uuid.uuid4()
        first = self.shadow(revision, request_key=shadow_key)
        second = self.shadow(revision, request_key=shadow_key)
        self.assertEqual(first, second)
        self.assertEqual(ShadowComparison.objects.count(), 1)
        with self.assertRaises(cases.CaseConflict):
            self.shadow(revision, request_key=shadow_key, value="المعاملات")

    def test_current_sources_are_required_for_preview_review_and_shadow_audit(self):
        revision, preview = self.approved()
        comparison = self.shadow(revision)["comparison"]
        self.answer("نسخة بشرية جديدة تلغي لقطة المقارنة")
        self.build()
        with self.assertRaises(cases.CaseConflict):
            governance.read_shadow(**self.common, comparison_id=comparison["id"])
        draft = self.revision()
        with self.assertRaises(cases.CaseConflict):
            self.decide(draft, preview)
        with self.assertRaises(cases.CaseConflict):
            self.preview(revision, expected_revision=2)
        self.assertEqual(ShadowComparison.objects.count(), 1)

    def test_default_off_independent_actions_and_cross_case_do_not_expand_rights(self):
        revision, _ = self.approved()
        self.authority.denied.add("DICTIONARY_USE")
        with self.assertRaises(cases.CaseConflict):
            governance.search(**self.common, revision_id=revision["id"], value=TERM)
        self.assertEqual(services.search(**self.common, value="المعاملات")["total"], 2)
        self.authority.denied.clear()
        other = self.new_case("سؤال خاص غير مخول")
        with self.assertRaises(cases.CaseConflict):
            governance.search(
                **{**self.common, "case_id": other["case_id"]},
                revision_id=revision["id"],
                value=TERM,
            )
        with override_settings(FATWA_SEARCH_GOVERNANCE_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                governance.search(**self.common, revision_id=revision["id"], value=TERM)
            self.assertEqual(services.search(**self.common, value="المعاملات")["total"], 2)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            with self.assertRaises(cases.CaseConflict):
                governance.search(**self.common, revision_id=revision["id"], value=TERM)

    def test_final_authority_revocation_rolls_back_shadow_receipt(self):
        revision, _ = self.approved()

        def revoke(values):
            if ShadowComparison.objects.exists():
                self.authority.denied.add("SEARCH")

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.shadow(revision)
        self.assertFalse(ShadowComparison.objects.exists())

    def test_late_real_retirement_after_candidate_invalidates_whole_projection(self):
        revision, _ = self.approved()
        original = governance._candidate

        def retire(*args, **kwargs):
            result = original(*args, **kwargs)
            self.decide(revision, action="RETIRE", ttl_minutes=0)
            return result

        with patch.object(governance, "_candidate", side_effect=retire):
            with self.assertRaises(cases.CaseConflict):
                governance.search(**self.common, revision_id=revision["id"], value=TERM)
        self.assertEqual(SynonymDecision.objects.count(), 1)
        self.assertEqual(
            governance.search(**self.common, revision_id=revision["id"], value=TERM)["total"], 2
        )

    def test_expiry_after_candidate_is_checked_at_final_pure_boundary(self):
        revision = self.revision()
        preview = self.preview(revision)
        approved = self.decide(revision, preview, ttl_minutes=1)
        original = governance._candidate
        clock = patch(
            "django.utils.timezone.now", return_value=approved["valid_until"] + timedelta(seconds=1)
        )

        def expire(*args, **kwargs):
            result = original(*args, **kwargs)
            clock.start()
            return result

        try:
            with patch.object(governance, "_candidate", side_effect=expire):
                with self.assertRaises(cases.CaseConflict):
                    governance.search(**self.common, revision_id=revision["id"], value=TERM)
        finally:
            clock.stop()

    def test_sql_rejects_null_required_keys_cross_version_pin_and_mutation(self):
        original = services._seal

        def missing_key(row):
            if isinstance(row, SynonymRevision):
                row.entries = deepcopy(row.entries)
                row.entries[0]["alternatives"] = None
            return original(row)

        with patch.object(services, "_seal", side_effect=missing_key):
            with self.assertRaises(IntegrityError):
                self.revision()
        revision = self.revision()

        def forged_pin(row):
            if isinstance(row, SynonymPreview):
                row.source_pin["generation_digest"] = "0" * 64
            return original(row)

        with patch.object(services, "_seal", side_effect=forged_pin):
            with self.assertRaises(IntegrityError):
                self.preview(revision)
        preview = self.preview(revision)
        self.decide(revision, preview)
        self.shadow(revision)
        for model in (SynonymRevision, SynonymPreview, SynonymDecision, ShadowComparison):
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    model.objects.update(digest="0" * 64)
