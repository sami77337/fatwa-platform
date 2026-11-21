"""Actual search, cached export, file bytes and derived public projections."""

from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services as answer_media
from apps.canonical_search import services as search
from apps.canonical_search import test_support as search_fixture
from apps.case_lifecycle import services as lifecycle
from apps.case_lifecycle.models import LifecycleEvent
from apps.case_lifecycle.tests import Authority as LifecycleAuthority
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseSource
from apps.library_preview.services import PreviewUnavailable
from apps.public_answer_media import public as recordings
from apps.public_answer_media import test_support as media_fixture
from apps.public_answer_media import views as media_views
from apps.public_collections import services as collections
from apps.public_collections import test_support as collection_fixture
from apps.public_knowledge import public as knowledge
from apps.public_knowledge import tests as knowledge_fixture
from apps.research_library import public as public_library
from apps.research_library import services as library
from apps.research_library import test_support as library_fixture
from apps.selected_exports import tests as export_fixture

from . import catalog, services
from .test_support import FEATURES, Fixture, SuppressionFixture


@override_settings(**FEATURES)
class LifecycleReaderTests(Fixture, TransactionTestCase):
    def test_soft_delete_does_not_convert_close_archive_or_reopen_and_hides_lifecycle_desk(self):
        authority = LifecycleAuthority([self.case.public_ref], self.directory.provider_id)
        with override_settings(
            FATWA_CASE_LIFECYCLE_ENABLED=True, FATWA_CASE_LIFECYCLE_AUTHORITY=authority
        ):
            before = lifecycle.desk(case_id=str(self.case.pk), **self.suppression_common("mufti"))
            self.change()
            with self.assertRaises(cases.CaseConflict):
                lifecycle.desk(case_id=str(self.case.pk), **self.suppression_common("mufti"))
            self.assertEqual(
                lifecycle.inbox(**self.suppression_common("mufti"))["counts"],
                {"OPEN": 0, "CLOSED": 0, "ARCHIVED": 0},
            )
            self.assertEqual(LifecycleEvent.objects.count(), 0)
            self.change("RESTORE")
            after = lifecycle.desk(case_id=str(self.case.pk), **self.suppression_common("mufti"))
            self.assertEqual(after["state"], before["state"])
            self.assertEqual(LifecycleEvent.objects.count(), 0)

    def test_lifecycle_returned_guard_rejects_deletion_from_its_last_callback(self):
        authority = LifecycleAuthority([self.case.public_ref], self.directory.provider_id)
        with override_settings(
            FATWA_CASE_LIFECYCLE_ENABLED=True, FATWA_CASE_LIFECYCLE_AUTHORITY=authority
        ):
            result = lifecycle.desk(case_id=str(self.case.pk), **self.suppression_common("mufti"))
            fired = False

            def late(values):
                nonlocal fired
                if not fired:
                    fired = True
                    self.change()

            authority.callback = late
            with self.assertRaises(catalog.SuppressionDenied):
                result["_guard"].check()
            authority.callback = None
            self.change("RESTORE")
            self.assertEqual(
                lifecycle.desk(case_id=str(self.case.pk), **self.suppression_common("mufti"))[
                    "state"
                ],
                "OPEN",
            )


@override_settings(**knowledge_fixture.FEATURES)
class KnowledgeSuppressionTests(
    SuppressionFixture, knowledge_fixture.CurationFixture, TransactionTestCase
):
    def test_exact_public_record_and_source_suppression_filter_navigation_and_sitemap(self):
        scholar, parent, child, presentation, translation = self.published()
        self.enable_suppression(
            [
                ("CASE", self.receipt["case_id"]),
                ("PUBLICATION", self.edition["id"]),
                ("PUBLIC_KNOWLEDGE", scholar["id"]),
            ],
            subjects=("publisher",),
        )
        original = list(CaseSource.objects.values())
        with knowledge.projection() as result:
            self.assertEqual(len(result.records), 5)
        self.change(kind="PUBLIC_KNOWLEDGE", identifier=scholar["id"], subject="publisher")
        self.assertEqual(self.page(scholar).status_code, 404)
        with knowledge.projection() as result:
            self.assertNotIn(scholar["id"], result.records)
            self.assertEqual(result.presentations, {})
        self.change(
            "RESTORE", kind="PUBLIC_KNOWLEDGE", identifier=scholar["id"], subject="publisher"
        )
        self.assertEqual(self.page(scholar).status_code, 200)
        self.change(kind="PUBLICATION", identifier=self.edition["id"], subject="publisher")
        with knowledge.projection() as result:
            self.assertEqual(result.records, {})
        self.assertNotContains(
            self.client.get("/library-preview/knowledge/sitemap.xml"), scholar["series_id"]
        )
        self.change(
            "RESTORE", kind="PUBLICATION", identifier=self.edition["id"], subject="publisher"
        )
        with knowledge.projection() as result:
            self.assertEqual(len(result.records), 5)
        self.assertEqual(list(CaseSource.objects.values()), original)


@override_settings(**collection_fixture.FEATURES)
class CollectionSuppressionTests(
    SuppressionFixture, collection_fixture.CollectionFixture, TransactionTestCase
):
    def test_saved_collection_never_bypasses_suppressed_member(self):
        row = self.release_collection(self.create_collection())
        self.enable_suppression([("PUBLICATION", self.edition["id"])], subjects=("publisher",))
        with collections.public_projection() as result:
            self.assertEqual(len(result), 1)
        self.change(kind="PUBLICATION", identifier=self.edition["id"], subject="publisher")
        with collections.public_projection() as result:
            self.assertEqual(result, [])
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        self.change(
            "RESTORE", kind="PUBLICATION", identifier=self.edition["id"], subject="publisher"
        )
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 200)


@override_settings(**media_fixture.FEATURES)
class MediaSuppressionTests(SuppressionFixture, media_fixture.MediaFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.transcript = self.review(self.save())
        self.recording = self.release(self.transcript)
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.url = f"/library-preview/recordings/{self.recording['id']}/audio/"
        self.enable_suppression(
            [
                ("ANSWER_PART", str(self.part.pk)),
                ("RECORDING_TRANSCRIPT", self.transcript["id"]),
                ("PUBLIC_MEDIA", self.recording["id"]),
            ],
            subjects=("publisher",),
        )

    def test_private_and_public_bytes_follow_source_without_physically_deleting_file(self):
        self.assertEqual(self.client.get(self.url, HTTP_RANGE="bytes=0-15").status_code, 206)
        self.change(kind="ANSWER_PART", identifier=str(self.part.pk), subject="publisher")
        with self.assertRaises(catalog.SuppressionDenied):
            answer_media.staff_read(
                part_id=str(self.part.pk),
                subject_id="editor",
                provider=self.directory,
                synthetic_fixtures_only=True,
            )
        self.assertEqual(self.client.get(self.url, HTTP_RANGE="bytes=0-15").status_code, 404)
        self.change(
            "RESTORE", kind="ANSWER_PART", identifier=str(self.part.pk), subject="publisher"
        )
        self.assertEqual(
            self.client.get(self.url, HTTP_RANGE="bytes=0-15").content, media_fixture.audio()[:16]
        )
        self.change(
            kind="RECORDING_TRANSCRIPT", identifier=self.transcript["id"], subject="publisher"
        )
        with (
            self.assertRaises(PreviewUnavailable),
            recordings.recording_projection(self.recording["id"]),
        ):
            pass
        self.change(
            "RESTORE",
            kind="RECORDING_TRANSCRIPT",
            identifier=self.transcript["id"],
            subject="publisher",
        )
        self.assertEqual(
            self.client.get(self.url, HTTP_RANGE="bytes=0-15").content, media_fixture.audio()[:16]
        )

    def test_late_public_range_projection_discards_bytes_after_new_deletion(self):
        plan = self.plan(kind="PUBLIC_MEDIA", identifier=self.recording["id"], subject="publisher")
        original = media_views._file_response

        def after_bytes(*args, **kwargs):
            response = original(*args, **kwargs)
            with services.apply(plan=plan, confirmed=True, **self.suppression_common("publisher")):
                pass
            return response

        with patch.object(media_views, "_file_response", side_effect=after_bytes):
            response = self.client.get(self.url, HTTP_RANGE="bytes=0-15")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Content-Range", response)
        self.assertNotIn(media_fixture.audio()[:16], response.content)
        self.change("RECONCILE", subject="publisher")
        self.change(
            "RESTORE", kind="PUBLIC_MEDIA", identifier=self.recording["id"], subject="publisher"
        )
        self.assertEqual(
            self.client.get(self.url, HTTP_RANGE="bytes=0-15").content, media_fixture.audio()[:16]
        )


@override_settings(**library_fixture.FEATURES)
class LibrarySuppressionTests(
    SuppressionFixture, library_fixture.LibraryFixture, TransactionTestCase
):
    def test_current_private_file_and_public_copy_have_no_old_byte_bypass(self):
        raw = "ملف أصلي محفوظ للحذف المنطقي".encode()
        record = self.release(
            self.write(file_bytes=raw, filename="source.txt", media_type="text/plain")
        )
        key = record["version_id"]
        self.enable_suppression([("LIBRARY_VERSION", key)], subjects=("editor",))
        with public_library.public_projection() as result:
            self.assertEqual(result.content(key)["raw"], raw)
        self.change(kind="LIBRARY_VERSION", identifier=key, subject="editor")
        self.assertEqual(library.browse(**self.common)["total"], 0)
        with self.assertRaises(catalog.SuppressionDenied):
            library.file_content(**self.common, version_id=key)
        with public_library.public_projection() as result:
            self.assertEqual(result.records, {})
        self.change("RESTORE", kind="LIBRARY_VERSION", identifier=key, subject="editor")
        self.assertEqual(library.file_content(**self.common, version_id=key)["raw"], raw)


@override_settings(**search_fixture.FEATURES)
class SearchSuppressionTests(SuppressionFixture, search_fixture.SearchFixture, TransactionTestCase):
    def test_saved_fts_generation_has_no_stale_snippet_count_or_open(self):
        self.answer("جواب خاص مع لفظ الزكاة المحفوظ")
        answer = AnswerRevision.objects.get(case_id=self.receipt["case_id"])
        self.build()
        self.enable_suppression([("ANSWER", str(answer.pk))], subjects=("editor",))
        before = self.search(value="الزكاة")
        self.assertEqual(before["total"], 2)
        hit = next(row for row in before["results"] if row["kind"] == "ANSWER")
        self.change(kind="ANSWER", identifier=str(answer.pk), subject="editor")
        current = self.search(value="الزكاة")
        self.assertEqual(current["total"], 1)
        self.assertNotIn("جواب خاص", repr(current))
        with self.assertRaises(cases.CaseConflict):
            search.open_source(
                **self.common, generation_id=hit["generation_id"], document_id=hit["document_id"]
            )
        self.change("RESTORE", kind="ANSWER", identifier=str(answer.pk), subject="editor")
        self.assertEqual(self.search(value="الزكاة")["total"], 2)


@override_settings(**export_fixture.FEATURES)
class ExportSuppressionTests(SuppressionFixture, export_fixture.ExportFixture, TransactionTestCase):
    def test_prebuilt_export_needs_current_source_after_suppression_and_restoration(self):
        selected = self.transcript_resource()
        job = self.prepare_export(selected=[selected])
        self.build(job)
        raw = self.download_export(job)["raw"]
        self.enable_suppression([("TRANSCRIPT_LINK", selected.identifier)], subjects=("editor",))
        self.change(kind="TRANSCRIPT_LINK", identifier=selected.identifier, subject="editor")
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)
        self.change(
            "RESTORE", kind="TRANSCRIPT_LINK", identifier=selected.identifier, subject="editor"
        )
        self.assertEqual(self.download_export(job)["raw"], raw)
