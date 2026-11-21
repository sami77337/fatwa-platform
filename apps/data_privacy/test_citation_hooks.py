"""Manual citations, original media and public derivatives keep separate exact grants."""

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.pdf_citations import services as pdf
from apps.pdf_citations import tests as pdf_fixture
from apps.precise_citations import services as precise
from apps.precise_citations import sources
from apps.precise_citations import test_http as native
from apps.precise_citations.boundary import scope
from apps.precise_citations.models import CitationSet
from apps.precise_citations.test_support import FEATURES, CitationFixture
from apps.timed_citations import services as timed
from apps.timed_citations import tests as timed_fixture
from tests.casework.test_http import hidden

from . import services
from .test_material_hooks import ExactGrants


@override_settings(**FEATURES)
class PrecisePrivacyTests(ExactGrants, CitationFixture, TransactionTestCase):
    login = native.CitationHTTPTests.login
    action = native.CitationHTTPTests.action
    add = native.CitationHTTPTests.add

    def setUp(self):
        super().setUp()
        self.record = self.review_citations(self.save_citations())
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH")

    def test_owner_source_search_and_export_are_current_independent_uses(self):
        with self.assertRaises(services.PrivacyDenied):
            precise.read(**self.common, set_id=self.record["id"])
        self.admit("ANSWER", self.record["answer_id"], "READ")
        with self.assertRaises(services.PrivacyDenied):
            precise.read(**self.common, set_id=self.record["id"])
        self.admit("LIBRARY_VERSION", self.material["version_id"], "READ")
        self.assertEqual(
            precise.read(**self.common, set_id=self.record["id"])["answer_text"], self.answer_text
        )
        with scope(**self.common) as guard:
            self.assertEqual(sources.choices(guard, self.common["case_id"]), [])
        self.admit("LIBRARY_VERSION", self.material["version_id"], "SEARCH")
        with scope(**self.common) as guard:
            self.assertEqual(len(sources.choices(guard, self.common["case_id"])), 1)
        with self.assertRaises(services.PrivacyDenied):
            precise.read(**self.common, set_id=self.record["id"], usage="EXPORT")
        self.admit("CASE", self.receipt["case_id"], "EXPORT")
        self.admit("ANSWER", self.record["answer_id"], "EXPORT")
        with self.assertRaises(services.PrivacyDenied):
            precise.read(**self.common, set_id=self.record["id"], usage="EXPORT")
        key = self.admit("LIBRARY_VERSION", self.material["version_id"], "EXPORT")[0]
        self.assertEqual(
            precise.read(**self.common, set_id=self.record["id"], usage="EXPORT")["answer_text"],
            self.answer_text,
        )
        del self.privacy.grants[key]
        with self.assertRaises(services.PrivacyDenied):
            precise.read(**self.common, set_id=self.record["id"], usage="EXPORT")

    def test_prior_answer_and_original_part_cannot_borrow_case_or_sibling_grants(self):
        # Only the fresh unrelated fixture is seeded while the feature is off;
        # existing classified targets remain protected under that setting too.
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=False):
            receipt, base = self.second_case()
            saved = media.save_multipart_answer(
                **base,
                text="جواب مصدر اصطناعي",
                files=[audio_fixture()],
                expected_revision=1,
                expected_evidence_version=1,
            )
            answer_id = saved["answers"][-1]["id"]
            cases.record_decision(
                **base,
                answer_id=answer_id,
                action="APPROVE",
                expected_revision=2,
                expected_evidence_version=1,
            )
        part = AnswerPart.objects.get(manifest__answer_id=answer_id, ordinal=2)

        def read():
            with scope(**self.common) as guard:
                return sources.select(
                    guard,
                    f"ANSWER:{answer_id}:{part.pk}",
                    owner_case_id=self.common["case_id"],
                    location=sources.locator("TIME", 0, 80),
                )[1]

        with self.assertRaises(services.PrivacyDenied):
            read()
        self.admit("CASE", receipt["case_id"], "READ", "SEARCH")
        self.admit("ANSWER", answer_id, "READ", "SEARCH")
        with self.assertRaises(services.PrivacyDenied):
            read()
        key = self.admit("ANSWER_PART", part.pk, "READ")[0]
        self.assertEqual(read()["raw"], audio_fixture()["raw"])
        with scope(**self.common) as guard:
            self.assertNotIn(
                f"ANSWER:{answer_id}:{part.pk}",
                [row["selection"] for row in sources.choices(guard, self.common["case_id"])],
            )
        self.admit("ANSWER_PART", part.pk, "SEARCH")
        with scope(**self.common) as guard:
            self.assertIn(
                f"ANSWER:{answer_id}:{part.pk}",
                [row["selection"] for row in sources.choices(guard, self.common["case_id"])],
            )
        del self.privacy.grants[key]
        with self.assertRaises(services.PrivacyDenied):
            read()

    def test_native_save_retains_new_revision_without_automatically_classifying_or_reading_it(self):
        self.admit("LIBRARY_VERSION", self.material["version_id"], "READ", "SEARCH")
        original = AnswerRevision.objects.get(pk=self.record["answer_id"]).text_sha256
        client, home = self.login()
        opened = self.action(client, home, "precise_open")
        self.assertEqual(opened.status_code, 200, opened.content)
        added = self.add(client, opened)
        saved = self.action(
            client,
            added,
            state=hidden(added, "state"),
            text=self.answer_text,
            command="save",
            confirmed="yes",
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertNotIn(self.answer_text.encode(), saved.content)
        self.assertContains(saved, "يلزم تصنيفه")
        self.assertEqual(CitationSet.objects.count(), 2)
        latest = CitationSet.objects.order_by("-answer__revision").first()
        self.assertFalse(services.recorded("ANSWER", str(latest.answer_id)))
        self.admit("ANSWER", latest.answer_id, "READ")
        self.assertContains(self.action(client, saved, "precise_open"), self.answer_text)
        self.assertEqual(
            AnswerRevision.objects.get(pk=self.record["answer_id"]).text_sha256, original
        )

    def test_last_citation_callback_revocation_discards_already_composed_source(self):
        self.admit("ANSWER", self.record["answer_id"], "READ")
        key = self.admit("LIBRARY_VERSION", self.material["version_id"], "READ")[0]
        with self.assertRaises(services.PrivacyDenied), scope(**self.common) as guard:
            precise.read_locked(guard, case_id=self.common["case_id"], set_id=self.record["id"])
            self.citation_authority.hook = lambda values: self.privacy.grants.pop(key, None)
        self.citation_authority.hook = None
        self.admit("LIBRARY_VERSION", self.material["version_id"], "READ")
        self.assertEqual(
            precise.read(**self.common, set_id=self.record["id"])["answer_text"], self.answer_text
        )


@override_settings(**FEATURES)
class PublicPrecisePrivacyTests(ExactGrants, CitationFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.record = self.review_citations(self.save_citations())
        cases.record_decision(
            **self.common,
            answer_id=self.record["answer_id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        configured = override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(
                self.receipt["public_ref"]
            )
        )
        configured.enable()
        self.addCleanup(configured.disable)
        edition = publications.create_edition(
            **self.common,
            expected_revision=3,
            expected_evidence_version=1,
            title="نسخة معلنة اصطناعية",
            category="موضوع تجريبي",
            body="نص النسخة المحررة للعرض العام",
        )
        for action, actor in (("REVIEW", "other"), ("APPROVE", "publisher")):
            publications.act(
                **{**self.common, "subject_id": actor},
                edition_id=edition["id"],
                action=action,
                reviewed=True,
            )
        self.edition = PublicationEdition.objects.get(pk=edition["id"])
        configured = override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=PreviewPolicy(
                (PublicationGrant(str(self.edition.pk), self.edition.content_sha256),),
                (),
                timezone.now() + timedelta(minutes=10),
                True,
            )
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.privacy_on()
        self.admit("PUBLICATION", self.edition.pk, "READ", "SEARCH", actor=None, level="PUBLIC")
        self.admit("CASE", self.receipt["case_id"], "PUBLISH", actor="publisher")
        self.admit("ANSWER", self.record["answer_id"], "PUBLISH", actor="publisher")
        self.key = self.admit(
            "LIBRARY_VERSION", self.material["version_id"], "PUBLISH", actor="publisher"
        )[0]
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.url = f"/library-preview/editions/{self.edition.pk}/"

    def test_public_http_uses_exact_publisher_purpose_while_native_source_keeps_its_mufti(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, self.edition.body)
        self.assertNotIn(self.answer_text.encode(), response.content)
        with self.assertRaises(services.PrivacyDenied):
            precise.read(**self.common, set_id=self.record["id"])
        self.admit("CASE", self.receipt["case_id"], "READ")
        self.admit("ANSWER", self.record["answer_id"], "READ")
        self.admit("LIBRARY_VERSION", self.material["version_id"], "READ")
        del self.privacy.grants[self.key]
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.admit("LIBRARY_VERSION", self.material["version_id"], "PUBLISH", actor="publisher")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_final_native_citation_callback_cannot_revoke_public_source_after_projection(self):
        original = preview._projection

        def late(*args, **kwargs):
            result = original(*args, **kwargs)
            self.citation_authority.hook = lambda values: self.privacy.grants.pop(self.key, None)
            return result

        with patch.object(preview, "_projection", side_effect=late):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.edition.body.encode(), response.content)


class MediaLocatorPrivacy:
    def setUp(self):
        super().setUp()
        self.record = self.propose()
        self.confirm(self.record)
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "READ")

    def test_owner_and_source_are_independent_before_history_counts_filename_and_bytes(self):
        result = self.reader.desk(**self.common)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["history"], [])
        self.admit("ANSWER", self.part.manifest.answer_id, "READ")
        result = self.reader.desk(**self.common)
        self.assertEqual(result["history"], [])
        with self.assertRaises(cases.CaseConflict):
            self.opened(self.record)
        key = self.admit("ATTACHMENT", self.attachment["id"], "READ")[0]
        result = self.reader.desk(**self.common)
        self.assertEqual(len(result["history"]), 1)
        expected = (self.pdf if hasattr(self, "pdf") else self.audio)["raw"]
        self.assertEqual(self.opened(self.record)["raw"], expected)
        del self.privacy.grants[key]
        self.assertEqual(self.reader.desk(**self.common)["history"], [])
        with self.assertRaises(cases.CaseConflict):
            self.opened(self.record)
        self.admit("ATTACHMENT", self.attachment["id"], "READ")
        self.assertEqual(self.opened(self.record)["raw"], expected)

    def test_late_native_media_deadline_callback_discards_prepared_original(self):
        self.admit("ANSWER", self.part.manifest.answer_id, "READ")
        key = self.admit("ATTACHMENT", self.attachment["id"], "READ")[0]
        original = self.rights.grant_deadline

        def late(**values):
            deadline = original(**values)
            self.privacy.grants.pop(key, None)
            return deadline

        with patch.object(self.rights, "grant_deadline", side_effect=late):
            with self.assertRaises(cases.CaseConflict):
                self.opened(self.record)


@override_settings(**timed_fixture.SETTINGS)
class TimedPrivacyTests(
    ExactGrants, MediaLocatorPrivacy, timed_fixture.Fixture, TransactionTestCase
):
    reader = timed


@override_settings(**pdf_fixture.SETTINGS)
class PdfPrivacyTests(ExactGrants, MediaLocatorPrivacy, pdf_fixture.Fixture, TransactionTestCase):
    reader = pdf
