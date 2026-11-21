"""Real library files, FTS rows and export artifacts obey independent privacy uses."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.canonical_search import services as search
from apps.canonical_search.test_support import FEATURES as SEARCH_FEATURES
from apps.canonical_search.test_support import SearchFixture
from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.library_preview.services import PreviewUnavailable
from apps.research_library import public
from apps.research_library import services as library
from apps.research_library.test_support import FEATURES as LIBRARY_FEATURES
from apps.research_library.test_support import LibraryFixture, bind_identity_snapshot
from apps.selected_exports.models import ExportJob
from apps.selected_exports.tests import FEATURES as EXPORT_FEATURES
from apps.selected_exports.tests import ExportFixture

from . import services
from .authority import Grant
from .catalog import locate
from .test_support import Authority


class ExactGrants:
    def privacy_on(self):
        bind_identity_snapshot(self.directory)
        self.privacy = Authority()
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.privacy,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def label(self, kind, identifier, *, level="CONFIDENTIAL"):
        target = locate(kind, identifier)
        rows = services.history(target)
        if rows and rows[-1].level == level:
            return target
        subject = getattr(self, "classifier", "editor")
        self.permit(
            target, level, "CLASSIFY", previous=rows[-1].level if rows else "", actor=subject
        )
        services.classify(
            kind=kind,
            identifier=identifier,
            level=level,
            note="قرار تصنيف بشري اصطناعي؛ لا قرار نشر أو تصدير",
            expected_digest=rows[-1].digest if rows else services.ZERO,
            expected_source_digest=target.source_digest,
            request_key=uuid.uuid4(),
            provider=self.directory,
            subject_id=subject,
            synthetic_fixtures_only=True,
        )
        return target

    def permit(self, target, level, action, *, actor="editor", previous=""):
        principal = (
            services.public_principal()
            if actor is None
            else services.staff_principal(self.directory, self.directory.resolve(actor))
        )
        values = dict(
            audience=principal.audience,
            provider_id=principal.provider_id,
            subject_id=principal.subject_id,
            auth_epoch=principal.auth_epoch,
            role=principal.role,
            case_ref=target.case_ref,
            target_kind=target.kind,
            target_id=target.identifier,
            source_digest=target.source_digest,
            classification=level,
            previous_level=previous,
            action=action,
        )
        key = self.privacy.key(values)
        self.privacy.grants[key] = Grant(timezone.now() + timedelta(minutes=10))
        return key

    def admit(self, kind, identifier, *actions, actor="editor", level="CONFIDENTIAL"):
        target = self.label(kind, identifier, level=level)
        return [self.permit(target, level, action, actor=actor) for action in actions]


@override_settings(**LIBRARY_FEATURES)
class LibraryPrivacyTests(ExactGrants, LibraryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.raw = "أصل مادة اصطناعية خاصة محفوظة\n".encode()
        self.record = self.release(
            self.write(
                file_bytes=self.raw, filename="private-original.txt", media_type="text/plain"
            )
        )
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH")

    def test_unclassified_material_is_filtered_before_count_filename_or_private_bytes(self):
        rows = library.browse(**self.common)
        self.assertEqual(rows["total"], 0)
        self.assertNotIn("private-original.txt", repr(rows))
        with self.assertRaises(services.PrivacyDenied):
            library.file_content(**self.common, version_id=self.record["version_id"])
        with public.public_projection() as snapshot:
            self.assertEqual(snapshot.records, {})
        self.admit("LIBRARY_VERSION", self.record["version_id"], "READ", "SEARCH")
        self.assertEqual(library.browse(**self.common)["total"], 1)
        self.assertEqual(
            library.file_content(**self.common, version_id=self.record["version_id"])["raw"],
            self.raw,
        )

    def test_public_label_does_not_replace_release_actor_or_download_grants(self):
        target = self.label("LIBRARY_VERSION", self.record["version_id"], level="PUBLIC")
        self.permit(target, "PUBLIC", "READ", actor=None)
        with public.public_projection() as snapshot:
            self.assertEqual(snapshot.records, {})
        self.permit(target, "PUBLIC", "PUBLISH", actor="publisher")
        with public.public_projection() as snapshot:
            self.assertEqual(snapshot.content(self.record["version_id"])["raw"], self.raw)
        with self.assertRaises(PreviewUnavailable), public.public_projection() as snapshot:
            snapshot.content(self.record["version_id"], usage="DOWNLOAD")
        key = self.permit(target, "PUBLIC", "EXPORT", actor=None)
        with public.public_projection() as snapshot:
            self.assertEqual(
                snapshot.content(self.record["version_id"], usage="DOWNLOAD")["raw"], self.raw
            )
        del self.privacy.grants[key]
        with self.assertRaises(PreviewUnavailable), public.public_projection() as snapshot:
            snapshot.content(self.record["version_id"], usage="OFFLINE")

    def test_last_library_callback_revocation_discards_public_record_then_positive_read(self):
        target = self.label("LIBRARY_VERSION", self.record["version_id"], level="PUBLIC")
        key = self.permit(target, "PUBLIC", "READ", actor=None)
        self.permit(target, "PUBLIC", "PUBLISH", actor="publisher")
        with self.assertRaises(PreviewUnavailable), public.public_projection() as snapshot:
            self.assertEqual(snapshot.content(self.record["version_id"])["raw"], self.raw)
            self.authority.hook = lambda values: self.privacy.grants.pop(key, None)
        self.authority.hook = None
        self.permit(target, "PUBLIC", "READ", actor=None)
        with public.public_projection() as snapshot:
            self.assertEqual(snapshot.content(self.record["version_id"])["raw"], self.raw)


@override_settings(**SEARCH_FEATURES)
class SearchPrivacyTests(ExactGrants, SearchFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.answer("جواب خاص مع لفظ الزكاة المحفوظ")
        self.answer_id = AnswerRevision.objects.get(case_id=self.receipt["case_id"]).pk
        self.build()
        self.privacy_on()

    def search(self, value="الزكاة", **changes):
        return super().search(value=value, **changes)

    def test_existing_index_cannot_reveal_unclassified_answer_snippet_or_count(self):
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH")
        result = self.search()
        self.assertEqual(result["total"], 1)
        self.assertEqual([row["kind"] for row in result["results"]], ["QUESTION"])
        self.assertNotIn("جواب خاص", repr(result))
        self.admit("ANSWER", self.answer_id, "SEARCH")
        result = self.search()
        self.assertEqual(result["total"], 2)
        row = next(row for row in result["results"] if row["kind"] == "ANSWER")
        with self.assertRaises(cases.CaseConflict):
            search.open_source(
                **self.common, generation_id=row["generation_id"], document_id=row["document_id"]
            )
        self.admit("ANSWER", self.answer_id, "READ")
        self.assertIn(
            "جواب خاص",
            search.open_source(
                **self.common, generation_id=row["generation_id"], document_id=row["document_id"]
            )["text"],
        )

    def test_case_read_does_not_authorize_search_and_late_privacy_change_discards_batch(self):
        self.admit("CASE", self.receipt["case_id"], "READ")
        with self.assertRaises(cases.CaseConflict):
            self.search()
        key = self.admit("CASE", self.receipt["case_id"], "SEARCH")[0]
        original = search.search_in_context

        def revoke_after_composition(*args, **kwargs):
            result = original(*args, **kwargs)
            del self.privacy.grants[key]
            return result

        with patch.object(search, "search_in_context", side_effect=revoke_after_composition):
            with self.assertRaises(cases.CaseConflict):
                self.search()
        self.admit("CASE", self.receipt["case_id"], "SEARCH")
        self.assertEqual(self.search()["total"], 1)


@override_settings(**EXPORT_FEATURES)
class ExportPrivacyTests(ExactGrants, ExportFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.selected = self.transcript_resource()
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH", "EXPORT")
        self.admit("TRANSCRIPT_LINK", self.selected.identifier, "READ", "SEARCH")

    def test_readable_transcript_requires_export_before_job_and_current_download(self):
        with self.assertRaises(cases.CaseConflict):
            self.prepare_export(selected=[self.selected])
        self.assertEqual(ExportJob.objects.count(), 0)
        key = self.admit("TRANSCRIPT_LINK", self.selected.identifier, "EXPORT")[0]
        job = self.prepare_export(selected=[self.selected])
        ready = self.build(job)
        self.assertEqual(ready["state"], "READY")
        raw = self.download_export(job)["raw"]
        self.assertGreater(len(raw), 100)
        del self.privacy.grants[key]
        with self.assertRaises(cases.CaseConflict):
            self.download_export(job)
        self.admit("TRANSCRIPT_LINK", self.selected.identifier, "EXPORT")
        self.assertEqual(self.download_export(job)["raw"], raw)
