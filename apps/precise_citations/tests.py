import uuid
from dataclasses import replace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.research_library import services as library
from apps.research_library.models import LibraryVersion

from . import integration, services, sources
from .boundary import scope
from .models import CitationAnchor, CitationReview, CitationSet
from .test_support import FEATURES, CitationFixture


@override_settings(**FEATURES)
class CitationTests(CitationFixture, TransactionTestCase):
    def test_exact_second_occurrence_review_and_readable_export(self):
        row = self.save_citations()
        self.assertEqual(row["entries"][0]["start"], self.answer_text.rindex("عبارة محددة"))
        self.assertIsNone(row["review"])
        with self.assertRaisesRegex(cases.CaseConflict, "human_review"):
            services.read(**self.common, set_id=row["id"], usage="EXPORT")
        reviewed = self.review_citations(row)
        exported = services.read(**self.common, set_id=row["id"], usage="EXPORT")
        self.assertEqual(reviewed["review"]["actor"], "other")
        self.assertIn("محارف المصدر 1–12", exported["entries"][0]["reference"])
        self.assertEqual(CitationSet.objects.count(), 1)

    def test_ambiguity_unicode_and_edited_phrase_never_silently_retarget(self):
        spans = services.occurrences("😀 كلمة كلمة", "كلمة")
        self.assertEqual([item["start"] for item in spans], [2, 7])
        entry = self.selection()
        with self.assertRaisesRegex(cases.CaseConflict, "phrase_changed"):
            self.save_citations(text="تغيير " + self.answer_text, selections=[entry])
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_current_source_cite_read_and_export_are_independent(self):
        row = self.review_citations(self.save_citations())
        self.authority.denied.add("EXPORT")
        services.read(**self.common, set_id=row["id"])
        with self.assertRaises(cases.CaseConflict):
            services.read(**self.common, set_id=row["id"], usage="EXPORT")
        self.authority.denied.clear()
        self.authority.denied.add("CITE")
        with self.assertRaises(cases.CaseConflict):
            services.read(**self.common, set_id=row["id"])

    def test_correction_creates_new_answer_and_requires_new_independent_review(self):
        old = self.review_citations(self.save_citations())
        original = CitationSet.objects.get(pk=old["id"]).canonical_payload
        selected = self.selection()
        selected.update(
            previous_id=old["entries"][0]["id"], correction_reason="تحديد أقرب موضع موثق"
        )
        selected["source"]["locator"] = sources.locator(
            "METADATA", limitation="لا توجد فقرة معنونة؛ النسخة محفوظة"
        )
        new = self.save_citations(selections=[selected], expected_revision=2)
        self.assertEqual(new["answer_revision"], 2)
        self.assertEqual(new["previous_id"], old["id"])
        self.assertIsNone(new["review"])
        self.assertEqual(CitationSet.objects.get(pk=old["id"]).canonical_payload, original)
        self.assertEqual(new["entries"][0]["previous_id"], old["entries"][0]["id"])
        with self.assertRaisesRegex(cases.CaseConflict, "independent_reviewer"):
            self.review_citations(new, subject_id="editor", expected_revision=3)

    def test_external_reference_is_honest_and_never_fetched(self):
        with scope(**self.common) as guard:
            pin, data = sources.select(
                guard,
                "EXTERNAL",
                owner_case_id=self.common["case_id"],
                location=sources.locator("METADATA", limitation="لا تتوفر نسخة رقمية"),
                descriptor=dict(
                    title="مصدر ورقي اصطناعي",
                    edition="طبعة موثقة يدويًا",
                    location="باب وصفي",
                    url="https://example.invalid/reference",
                    limitation="رابط أدخله المحرر ولم يفحص",
                ),
            )
        entry = services.anchor(
            self.answer_text, start=0, end=5, phrase=self.answer_text[:5], source=pin
        )
        row = self.save_citations(selections=[entry])
        self.assertEqual(data["raw"], b"")
        self.assertEqual(data["text"], "")
        self.assertIn("باب وصفي", row["entries"][0]["reference"])
        self.assertNotIn("example.invalid", row["entries"][0]["reference"])

    def test_exact_prior_answer_is_preserved_and_later_correction_shown_separately(self):
        other, other_base = self.second_case()
        first = cases.save_answer(
            **other_base, text="جواب سابق اصطناعي", expected_revision=1, expected_evidence_version=1
        )
        first_id = first["answers"][-1]["id"]
        cases.record_decision(
            **other_base,
            answer_id=first_id,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        with scope(**self.common) as guard:
            pin, _ = sources.select(
                guard,
                "ANSWER:" + first_id,
                owner_case_id=self.common["case_id"],
                location=sources.locator("TEXT", 0, 5),
            )
        selected = self.selection()
        selected["source"] = pin
        row = self.save_citations(selections=[selected])
        newer = cases.save_answer(
            **other_base, text="تصحيح لاحق مستقل", expected_revision=3, expected_evidence_version=1
        )
        cases.record_decision(
            **other_base,
            answer_id=newer["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=4,
            expected_evidence_version=1,
        )
        data = services.read(**self.common, set_id=row["id"])
        self.assertEqual(data["entries"][0]["source"]["id"], first_id)
        self.assertEqual(data["entries"][0]["corrections"][0]["text"], "تصحيح لاحق مستقل")
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({self.receipt["public_ref"]})
        )
        with self.assertRaises(cases.CaseConflict):
            services.read(**self.common, set_id=row["id"])

    def test_same_request_replays_and_stale_or_different_request_does_not(self):
        key = uuid.uuid4()
        selected = self.selection()
        first = self.save_citations(request_key=key, selections=[selected])
        same = self.save_citations(request_key=key, selections=[selected])
        self.assertEqual(first["id"], same["id"])
        with self.assertRaises(cases.CaseConflict):
            self.save_citations(request_key=key, text=self.answer_text + "تغيير")
        with self.assertRaises(cases.CaseConflict):
            self.save_citations()
        self.assertEqual(CitationSet.objects.count(), 1)

    def test_sql_immutable_ledger_and_wrong_source_owner(self):
        row = self.save_citations()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CitationAnchor.objects.filter(citation_set_id=row["id"]).update(phrase="تبديل")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CitationSet.objects.filter(pk=row["id"]).delete()
        self.assertEqual(
            CitationAnchor.objects.get(citation_set_id=row["id"]).phrase, "عبارة محددة"
        )

    def test_final_source_callback_identity_revoke_denies_whole_read(self):
        row = self.save_citations()
        fired = False

        def late(values):
            nonlocal fired
            if values["action"] == "READ" and not fired:
                fired = True
                self.directory.identities["editor"] = replace(
                    self.directory.identities["editor"], active=False
                )

        self.authority.hook = late
        with self.assertRaises(cases.CaseConflict):
            services.read(**self.common, set_id=row["id"])

    def test_read_boundary_detects_history_changes_after_projection(self):
        row = self.save_citations()
        with self.assertRaisesRegex(cases.CaseConflict, "projection_changed"):
            with scope(**self.common) as guard:
                services.read_locked(guard, case_id=self.common["case_id"], set_id=row["id"])
                self.review_citations(row)

    def test_library_new_version_never_changes_existing_pin(self):
        row = self.save_citations()
        old = LibraryVersion.objects.get(pk=self.material["version_id"])
        library.write_material(
            **self.common,
            namespace=old.item.namespace,
            external_id=old.item.external_id,
            payload={**old.payload, "recorded_text": "مصدر معدل آخر"},
            expected_version=1,
            expected_revision=2,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
        )
        data = services.read(**self.common, set_id=row["id"])
        self.assertEqual(data["entries"][0]["source"]["id"], self.material["version_id"])

    def test_canonical_hook_requires_review_and_outer_lifetime(self):
        row = self.save_citations()
        answer = AnswerRevision.objects.get(pk=row["answer_id"])
        with self.assertRaisesRegex(cases.CaseConflict, "outer_use_boundary"):
            integration.require_for_answer(
                answer, actor=self.directory.identities["editor"], provider=self.directory
            )
        from apps.delivery_queue.services import synthetic_queue_atomic

        with synthetic_queue_atomic(), integration.answer_use_boundary():
            with self.assertRaisesRegex(cases.CaseConflict, "human_review"):
                integration.validate_for_approval(
                    answer, actor=self.directory.identities["editor"], provider=self.directory
                )
        self.review_citations(row)
        with synthetic_queue_atomic(), integration.answer_use_boundary():
            integration.validate_for_approval(
                answer, actor=self.directory.identities["editor"], provider=self.directory
            )
        self.assertEqual(CitationReview.objects.count(), 1)

    def test_flags_missing_authority_and_directory_generation_fail_closed(self):
        with (
            override_settings(FATWA_PRECISE_CITATIONS_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.save_citations()
        with (
            override_settings(FATWA_PRECISE_CITATIONS_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.save_citations()
        with (
            patch.object(self.directory, "projection_epoch", return_value=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.save_citations()
