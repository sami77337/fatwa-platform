"""V9 research workflow: synthetic PostgreSQL, real forms and immutable history."""

from dataclasses import replace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from tests.casework.test_http import Directory

from . import composer_tests, services
from . import tests as citation_tests
from .models import AnswerCitation, CitationCorrection


@override_settings(FATWA_CASE_CITATIONS_ENABLED=True)
class ResearchServiceTests(TransactionTestCase):
    setUp = citation_tests.CitationTests.setUp
    save = citation_tests.CitationTests.save
    selection = citation_tests.CitationTests.selection

    def test_suggestions_are_existing_arabic_matches_and_never_write(self):
        proposals = services.suggest_sources(**self.common, edition_id=self.edition, query="فرع")
        self.assertEqual(len(proposals), 2)
        self.assertEqual(proposals[0]["source"]["heading_title"], "فَرْعٌ تَجْرِيبِيّ")
        self.assertEqual(proposals[0]["status"], "PROPOSED_REQUIRES_HUMAN_REVIEW")
        self.assertEqual(services.suggest_sources(**self.common, query=""), [])
        self.assertEqual(
            services.suggest_sources(**self.common, edition_id=self.edition, query="نص غير موجود"),
            [],
        )
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(CitationCorrection.objects.count(), 0)

    def test_correction_records_previous_source_reason_actor_and_time(self):
        self.save()
        old = AnswerCitation.objects.get()
        self.save(
            2,
            selections=[self.selection(3)],
            corrections=[
                dict(ordinal=1, previous_id=str(old.pk), reason="تصحيح الموضع بعد المراجعة البشرية")
            ],
        )
        change = CitationCorrection.objects.get()
        self.assertEqual(change.previous_id, old.pk)
        self.assertNotEqual(change.citation_id, old.pk)
        history = services.read_citation_history(**self.common)
        self.assertEqual([v["revision"] for v in history["revisions"]], [2, 1])
        latest = history["revisions"][0]
        self.assertEqual(latest["subject_id"], self.common["subject_id"])
        self.assertIsNotNone(latest["created_at"])
        self.assertEqual(latest["citations"][0]["correction"]["previous_revision"], 1)
        self.assertEqual(history["revisions"][1]["citations"][0]["source"]["source_row_id"], 2)
        self.assertEqual(
            services.read_citation_history(**self.common, before_revision=2)["revisions"][0][
                "revision"
            ],
            1,
        )
        # Read an old snapshot honestly when the live catalog cannot be resolved.
        with patch.object(services, "_source", side_effect=cases.CaseConflict("unavailable")):
            history = services.read_citation_history(**self.common)
        self.assertFalse(history["revisions"][0]["citations"][0]["current_source_available"])
        self.assertEqual(history["revisions"][1]["citations"][0]["source"]["source_row_id"], 2)

    def test_invalid_or_stale_correction_rolls_back_answer_and_approval(self):
        self.save()
        old = AnswerCitation.objects.get()
        cases.record_decision(
            **self.common,
            answer_id=old.answer_id,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        for change in (
            dict(ordinal=0, previous_id=str(old.pk), reason="سبب"),
            dict(ordinal=1, previous_id=str(old.pk), reason=" "),
            dict(ordinal=1, previous_id=str(old.pk), reason="x" * 2001),
            dict(ordinal=1, previous_id="00000000-0000-0000-0000-000000000000", reason="سبب"),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.save(3, selections=[self.selection(3)], corrections=[change])
            self.assertEqual(AnswerRevision.objects.count(), 1)
            self.assertEqual(Case.objects.get().approved_answer_id, old.answer_id)
        self.save(3, selections=[self.selection(3)])
        with self.assertRaises(cases.CaseConflict):
            self.save(4, corrections=[dict(ordinal=1, previous_id=str(old.pk), reason="قديم")])
        self.assertEqual(AnswerRevision.objects.count(), 2)

    def test_correction_guard_rejects_updates_deletes_late_and_cross_case_inserts(self):
        self.save()
        old = AnswerCitation.objects.get()
        self.save(
            2,
            selections=[self.selection(3)],
            corrections=[dict(ordinal=1, previous_id=str(old.pk), reason="تصحيح")],
        )
        change = CitationCorrection.objects.get()
        for mutation in (
            lambda: CitationCorrection.objects.filter(pk=change.pk).update(reason="طمس"),
            lambda: CitationCorrection.objects.filter(pk=change.pk).delete(),
            lambda: CitationCorrection.objects.create(
                citation=old, previous=change.citation, reason="عكس التاريخ"
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                mutation()
        self.save(3, selections=[self.selection(4)])
        latest = AnswerCitation.objects.order_by("-created_at").first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CitationCorrection.objects.create(
                citation=latest, previous=change.citation, reason="إضافة متأخرة"
            )
        other = cases.intake_case(
            original_question="قضية ثانية اصطناعية",
            source_event_id="second",
            requester_id="second",
            idempotency_key="second",
            synthetic_fixtures_only=True,
        )
        directory = Directory()
        directory.grant(other["public_ref"])
        with self.assertRaises(cases.CaseConflict):
            services.save_cited_answer(
                case_id=other["case_id"],
                provider=directory,
                subject_id=directory.current.subject_id,
                text="جواب",
                selections=[self.selection()],
                corrections=[dict(ordinal=1, previous_id=str(latest.pk), reason="ربط قضية أخرى")],
                expected_revision=1,
                expected_evidence_version=1,
                synthetic_fixtures_only=True,
            )

    def test_database_rejects_forged_cross_case_correction_inside_new_answer_transaction(self):
        self.save()
        foreign = AnswerCitation.objects.get()
        second = cases.intake_case(
            original_question="قضية مستقلة",
            source_event_id="cross-sql",
            requester_id="cross-sql",
            idempotency_key="cross-sql",
            synthetic_fixtures_only=True,
        )
        directory = Directory()
        directory.grant(second["public_ref"])
        original_selection = self.selection()
        replacement_selection = self.selection(3)
        self.common.update(
            case_id=second["case_id"], provider=directory, subject_id=directory.current.subject_id
        )
        self.save(selections=[original_selection])
        own = AnswerCitation.objects.get(answer__case_id=second["case_id"])
        create = CitationCorrection.objects.create

        def forged_create(**kwargs):
            return create(**{**kwargs, "previous": foreign})

        with patch.object(CitationCorrection.objects, "create", side_effect=forged_create):
            with self.assertRaises(IntegrityError):
                self.save(
                    2,
                    selections=[replacement_selection],
                    corrections=[
                        dict(ordinal=1, previous_id=str(own.pk), reason="محاولة ربط عابر للقضايا")
                    ],
                )
        self.assertEqual(AnswerRevision.objects.filter(case_id=second["case_id"]).count(), 1)
        self.assertEqual(CitationCorrection.objects.count(), 0)

    def test_injected_failure_rolls_back_whole_answer(self):
        self.save()
        old = AnswerCitation.objects.get()
        with patch.object(CitationCorrection.objects, "create", side_effect=IntegrityError("fail")):
            with self.assertRaises(IntegrityError):
                self.save(
                    2,
                    selections=[self.selection(3)],
                    corrections=[dict(ordinal=1, previous_id=str(old.pk), reason="تصحيح")],
                )
        self.assertEqual(Case.objects.get().revision, 2)
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(AnswerCitation.objects.count(), 1)

    def test_disabled_and_revoked_scopes_do_not_expose_suggestions_or_history(self):
        self.save()
        directory = Directory()
        common = {**self.common, "provider": directory, "subject_id": directory.current.subject_id}
        for operation in (services.read_citation_history, services.suggest_sources):
            with self.assertRaises(cases.CaseConflict):
                operation(**common)
            with override_settings(FATWA_CASE_CITATIONS_ENABLED=False):
                with self.assertRaises(cases.CaseConflict):
                    operation(**self.common)

    @override_settings(FATWA_ANSWER_MEDIA_ENABLED=True, FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True)
    def test_correction_preserves_files_and_closes_approval_and_private_availability(self):
        directory = Directory()
        directory.grant(self.receipt["public_ref"])
        self.common.update(provider=directory, subject_id=directory.current.subject_id)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            self.save()
            media.save_multipart_answer(
                **self.common,
                expected_revision=2,
                expected_evidence_version=1,
                text="جواب بملف",
                files=[
                    dict(raw=b"synthetic answer", filename="answer.txt", media_type="text/plain")
                ],
            )
            previous = AnswerRevision.objects.order_by("-revision").first()
            old = AnswerCitation.objects.get(answer=previous)
            part = AnswerPart.objects.get(manifest__answer=previous, ordinal=2)
            cases.record_decision(
                **self.common,
                answer_id=previous.pk,
                action="APPROVE",
                expected_revision=3,
                expected_evidence_version=1,
            )
            manifest = AnswerManifest.objects.get(answer=previous)
            media.release_private(
                **self.common,
                expected_revision=4,
                expected_evidence_version=1,
                manifest_sha256=manifest.sha256,
                confirmed=True,
            )
            media.requester_snapshot(token=self.receipt["token"], synthetic_fixtures_only=True)
            self.save(
                4,
                selections=[self.selection(3)],
                corrections=[
                    dict(ordinal=1, previous_id=str(old.pk), reason="تغير المصدر المقصود")
                ],
            )
            current = AnswerRevision.objects.order_by("-revision").first()
            copied = AnswerPart.objects.get(manifest__answer=current, ordinal=2)
            self.assertEqual(bytes(copied.original), bytes(part.original))
            self.assertEqual(copied.sha256, part.sha256)
            self.assertNotEqual(copied.pk, part.pk)
            self.assertIsNone(Case.objects.get().approved_answer_id)
            self.assertEqual(PrivateAnswerRelease.objects.count(), 1)
            self.assertFalse(PrivateAnswerRelease.objects.filter(manifest__answer=current).exists())
            with self.assertRaises(cases.CaseConflict):
                media.requester_snapshot(token=self.receipt["token"], synthetic_fixtures_only=True)


@override_settings(
    FATWA_CASE_CITATIONS_ENABLED=True,
    FATWA_CASEWORK_WEB_ENABLED=True,
    ROOT_URLCONF="apps.case_citations.urls",
)
class ResearchFormTests(TransactionTestCase):
    setUp = composer_tests.ComposerTests.setUp
    open = composer_tests.ComposerTests.open
    submit = composer_tests.ComposerTests.submit

    def test_arabic_proposal_preview_return_accept_keeps_draft_and_requires_review(self):
        self.page = self.submit("suggest", query="فرع")
        self.assertContains(self.page, "اقتراحات غير معتمدة")
        self.assertContains(self.page, "(0/12)")
        self.page = self.submit(f"open:{self.edition}:2", query="فرع", page="2")
        self.assertContains(self.page, "معاينة المصدر الموثق")
        self.assertContains(self.page, "مسودة بشرية")
        self.page = self.submit("return", query="فرع", page="2")
        self.assertContains(self.page, 'value="فرع"')
        self.assertContains(self.page, 'value="2"')
        self.assertNotContains(self.page, "معاينة المصدر الموثق")
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(self.submit(f"accept:{self.edition}:3").status_code, 400)
        self.page = self.submit(f"accept:{self.edition}:2")
        self.assertContains(self.page, "(1/12)")
        self.assertEqual(self.submit("save").status_code, 400)
        self.assertEqual(self.submit("save", confirm="yes").status_code, 200)

    def test_reorder_notes_correction_history_and_second_save_use_current_lineage(self):
        self.page = self.submit(f"add:{self.edition}:2")
        self.page = self.submit(f"add:{self.edition}:3", editorial_note="ملاحظة ثانية")
        self.page = self.submit("up:1")
        self.page = self.submit("save", confirm="yes")
        self.assertEqual(
            [r["source"]["source_row_id"] for r in services.read_citations(**self.common)], [3, 2]
        )
        self.page = self.submit("correct:0")
        self.page = self.submit(f"replace:{self.edition}:4", editorial_note="تصحيح بشري <unsafe>")
        self.assertContains(self.page, "تصحيح بشري &lt;unsafe&gt;")
        self.page = self.submit("save", confirm="yes")
        self.assertEqual(self.page.status_code, 200, self.page.content)
        self.page = self.submit("history:latest")
        self.assertContains(self.page, "سبب التصحيح البشري")
        self.assertContains(self.page, "ملاحظة ثانية")
        self.assertContains(self.page, "مسودة بشرية")
        self.page = self.submit("correct:0")
        self.page = self.submit(f"replace:{self.edition}:5", editorial_note="تصحيح لاحق")
        self.page = self.submit("save", confirm="yes")
        self.assertEqual(self.page.status_code, 200, self.page.content)
        self.assertEqual(CitationCorrection.objects.count(), 2)
        self.assertEqual(
            CitationCorrection.objects.order_by("-pk").first().previous.answer.revision, 2
        )

    def test_unsaved_correction_invalid_commands_and_stale_correction_fail_closed(self):
        self.page = self.submit(f"add:{self.edition}:2")
        self.assertEqual(self.submit("correct:0").status_code, 400)
        self.assertEqual(self.submit("up:0").status_code, 400)
        self.assertEqual(self.submit(f"replace:{self.edition}:3").status_code, 400)
        self.page = self.submit("save", confirm="yes")
        self.page = self.submit("correct:0")
        self.assertEqual(
            self.submit(f"replace:{self.edition}:3", editorial_note="").status_code, 409
        )
        self.page = self.submit(f"replace:{self.edition}:3", editorial_note="تصحيح")
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع جديدة",
            expected_revision=2,
            synthetic_fixtures_only=True,
        )
        failed = self.submit("save", confirm="yes")
        self.assertContains(failed, "مسودة بشرية", status_code=409)
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(CitationCorrection.objects.count(), 0)

    def test_revocation_blocks_preview_history_and_proposals(self):
        self.directory.current = replace(self.directory.current, case_keys=frozenset())
        for command in (f"open:{self.edition}:2", "history:latest", "suggest"):
            response = self.submit(command, query="فرع")
            self.assertIn(response.status_code, (403, 404))
            self.assertNotContains(response, "فَرْعٌ تَجْرِيبِيّ", status_code=response.status_code)
