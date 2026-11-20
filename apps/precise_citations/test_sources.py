import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.casework import services as cases
from apps.research_library.test_support import payload

from . import integration, services, sources
from .boundary import scope
from .models import CitationSet
from .test_support import FEATURES, CitationFixture


@override_settings(**FEATURES)
class CitationSourceTests(CitationFixture, TransactionTestCase):
    def test_exact_prior_audio_part_and_time_open_original_not_a_newer_part(self):
        receipt, other = self.second_case()
        saved = media.save_multipart_answer(
            **other,
            text="جواب سابق بصوت",
            files=[audio_fixture()],
            expected_revision=1,
            expected_evidence_version=1,
        )
        answer = saved["answers"][-1]["id"]
        cases.record_decision(
            **other,
            answer_id=answer,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        part = AnswerPart.objects.get(manifest__answer_id=answer, ordinal=2)
        with scope(**self.common) as guard:
            choice = next(
                value
                for value in sources.choices(guard, self.common["case_id"])
                if value["selection"].endswith(str(part.pk))
            )
            pin, data = sources.select(
                guard,
                choice["selection"],
                owner_case_id=self.common["case_id"],
                location=sources.locator("TIME", 0, 80),
            )
        self.assertEqual(data["raw"], audio_fixture()["raw"])
        self.assertEqual(data["media_fragment"], "#t=0,0.08")
        entry = self.selection()
        entry["source"] = pin
        record = self.save_citations(selections=[entry])
        media.save_multipart_answer(
            **other,
            text="جواب صوتي جديد",
            files=[audio_fixture()],
            expected_revision=3,
            expected_evidence_version=1,
        )
        row = services.read(**self.common, set_id=record["id"])
        self.assertEqual(row["entries"][0]["source"]["part_id"], str(part.pk))
        self.citation_authority.denied.add(("READ_SOURCE", str(part.pk)))
        with self.assertRaises(cases.CaseConflict):
            services.read(**self.common, set_id=record["id"])

    def test_metadata_only_library_edition_has_explicit_fallback_no_fabricated_text(self):
        descriptive = self.approve(
            self.write(payload=payload(title="مرجع وصفي فقط", source_locator="باب موثق يدويًا")),
            uses=["CITE", "EXPORT"],
        )
        with scope(**self.common) as guard:
            pin, data = sources.select(
                guard,
                "LIBRARY:" + descriptive["version_id"],
                owner_case_id=self.common["case_id"],
                location=sources.locator("METADATA", limitation="لا يوجد أصل رقمي متاح"),
            )
            self.assertEqual(data["text"], "")
            self.assertEqual(data["raw"], b"")
            self.assertIn("باب موثق يدويًا", data["reference"])
        with self.assertRaisesRegex(cases.CaseConflict, "text_locator_unavailable"):
            with scope(**self.common) as guard:
                sources.select(
                    guard,
                    "LIBRARY:" + descriptive["version_id"],
                    owner_case_id=self.common["case_id"],
                    location=sources.locator("TEXT", 0, 1),
                )

    def test_unknown_page_or_range_denies_and_explicit_documented_fallback_is_distinct(self):
        entry = self.selection()
        invalid = {**entry["source"], "locator": sources.locator("PAGE", 900, 900)}
        with self.assertRaisesRegex(cases.CaseConflict, "page_unavailable"):
            with scope(**self.common) as guard:
                sources.read(guard, invalid, owner_case_id=self.common["case_id"])
        fallback = {
            **entry["source"],
            "locator": sources.locator("METADATA", limitation="النص محفوظ؛ لا توجد صفحات مرقمة"),
        }
        with scope(**self.common) as guard:
            result = sources.read(guard, fallback, owner_case_id=self.common["case_id"])
        self.assertEqual(result["raw"], "مصدر اصطناعي دقيق محفوظ للإحالة".encode())
        self.assertEqual(result["limitation"], "النص محفوظ؛ لا توجد صفحات مرقمة")

    def test_concurrent_same_revision_has_one_canonical_winner(self):
        selected = self.selection()

        def save():
            close_old_connections()
            try:
                return self.save_citations(selections=[selected], request_key=uuid.uuid4())["id"]
            except cases.CaseConflict:
                return None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: save(), range(2)))
        self.assertEqual(sum(value is not None for value in values), 1)
        self.assertEqual(CitationSet.objects.count(), 1)

    def test_outer_canonical_projection_catches_late_source_rights_and_actor_changes(self):
        row = self.review_citations(self.save_citations())
        approved = cases.record_decision(
            **self.common,
            answer_id=row["answer_id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        from apps.casework.models import AnswerRevision
        from apps.delivery_queue.services import synthetic_queue_atomic

        answer = AnswerRevision.objects.get(pk=approved["approved_answer_id"])
        with self.assertRaises(cases.CaseConflict):
            with synthetic_queue_atomic(), integration.answer_use_boundary():
                integration.require_for_answer(answer)
                self.authority.denied.add("CITE")
        self.authority.denied.clear()
        with self.assertRaises(cases.CaseConflict):
            with synthetic_queue_atomic(), integration.answer_use_boundary():
                integration.require_for_answer(answer)
                self.directory.identities["editor"] = replace(
                    self.directory.identities["editor"], active=False
                )

    def test_late_equal_authority_replacement_cannot_pass_by_value_equality(self):
        row = self.save_citations()
        from .test_support import FixtureAuthority

        class EqualAuthority(FixtureAuthority):
            def __eq__(self, other):
                return True

        with self.assertRaisesRegex(cases.CaseConflict, "projection_changed"):
            with scope(**self.common) as guard:
                services.read_locked(guard, case_id=self.common["case_id"], set_id=row["id"])
                with override_settings(
                    FATWA_PRECISE_CITATIONS_AUTHORITY=EqualAuthority(self.receipt["public_ref"])
                ):
                    guard.final_pins()

    def test_untrusted_external_urls_are_rejected_without_fetch(self):
        for url in (
            "javascript:alert(1)",
            "http://example.invalid",
            "https://user:pass@example.invalid",
            "https://example.invalid/ bad",
        ):
            with self.subTest(url=url), self.assertRaises(cases.CaseConflict):
                sources.external("عنوان", "نسخة", "موضع", url, "غير متحقق")

    def test_unapproved_sources_are_not_listed_or_credited_as_readable(self):
        pending = self.write(payload=payload(title="مصدر لم يراجع"))
        with scope(**self.common) as guard:
            choices = sources.choices(guard, self.common["case_id"])
        self.assertNotIn(
            "LIBRARY:" + pending["version_id"], [item["selection"] for item in choices]
        )

    def test_original_reader_callback_cannot_revoke_after_final_authority_check(self):
        row = self.save_citations()
        from apps.research_library import services as library

        real = library._raw

        def changed(blob):
            value = real(blob)
            self.citation_authority.denied.add("READ_SOURCE")
            return value

        with self.assertRaisesRegex(cases.CaseConflict, "projection_changed"):
            with scope(**self.common) as guard:
                services.read_locked(guard, case_id=self.common["case_id"], set_id=row["id"])
                with patch.object(library, "_raw", side_effect=changed):
                    guard.final_pins()

    def test_restored_citations_cannot_disappear_when_editing_app_is_omitted(self):
        row = self.review_citations(self.save_citations())
        installed = [name for name in settings.INSTALLED_APPS if name != "apps.precise_citations"]
        with (
            override_settings(INSTALLED_APPS=installed),
            self.assertRaisesRegex(cases.CaseConflict, "schema_unavailable"),
        ):
            cases.record_decision(
                **self.common,
                answer_id=row["answer_id"],
                action="APPROVE",
                expected_revision=2,
                expected_evidence_version=1,
            )

    def test_canonical_write_cannot_rebase_another_cases_source_snapshot(self):
        from apps.casework.models import AnswerRevision
        from apps.delivery_queue.services import synthetic_queue_atomic

        _, other = self.second_case()
        saved = cases.save_answer(
            **other, text="جواب مصدر قديم", expected_revision=1, expected_evidence_version=1
        )
        target = saved["answers"][-1]["id"]
        cases.record_decision(
            **other,
            answer_id=target,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        with scope(**self.common) as guard:
            pin, _ = sources.select(
                guard,
                "ANSWER:" + target,
                owner_case_id=self.common["case_id"],
                location=sources.locator("TEXT", 0, 5),
            )
        selected = self.selection()
        selected["source"] = pin
        own = self.review_citations(self.save_citations(selections=[selected]))
        cases.record_decision(
            **self.common,
            answer_id=own["answer_id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        corrected = cases.save_answer(
            **other, text="تصحيح مصدر لاحق", expected_revision=3, expected_evidence_version=1
        )
        answer = AnswerRevision.objects.get(pk=own["answer_id"])
        with self.assertRaisesRegex(cases.CaseConflict, "projection_changed"):
            with synthetic_queue_atomic(), integration.answer_use_boundary():
                integration.require_for_answer(answer)
                cases.record_decision(
                    **other,
                    answer_id=corrected["answers"][-1]["id"],
                    action="APPROVE",
                    expected_revision=4,
                    expected_evidence_version=1,
                )
