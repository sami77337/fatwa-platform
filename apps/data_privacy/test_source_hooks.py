"""Existing source originals, public fatwas and citation metadata retain privacy."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.library_preview.tests import ENABLED as PREVIEW_FEATURES
from apps.library_preview.tests import PreviewFixture
from apps.source_case_intake import desk_services
from apps.source_case_intake import http_tests as intake_http
from apps.source_case_intake import services as intake
from apps.source_rights import services as rights
from apps.source_rights.tests import Authority as RightsAuthority
from tests.casework.test_http import post

from . import services
from .catalog import locate
from .test_material_hooks import ExactGrants
from .test_support import Authority, PrivacyFixture


@override_settings(**PREVIEW_FEATURES)
class PublicSourcePrivacyTests(ExactGrants, PreviewFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.edition_row = PublicationEdition.objects.get(pk=self.edition["id"])
        with override_settings(
            FATWA_SOURCE_RIGHTS_ENABLED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
        ):
            self.source_id = rights.register(
                **self.common, kind="TOC_METADATA", target_id=self.heading.pk
            )["id"]
        self.privacy_on()

    def public_copy(self):
        self.admit("PUBLICATION", self.edition["id"], "READ", "SEARCH", actor=None, level="PUBLIC")
        self.admit("ANSWER", self.edition_row.answer_id, "PUBLISH", actor="publisher")
        return self.admit("SOURCE_VERSION", self.source_id, "PUBLISH", actor="publisher")

    def test_public_copy_and_current_original_publish_are_independent_before_metadata(self):
        self.label("PUBLICATION", self.edition["id"], level="PUBLIC")
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        self.public_copy()
        result = preview.read(self.edition["id"])
        self.assertEqual(result["title"], self.edition_row.title)
        self.assertEqual(result["relations"]["references"], [])
        self.assertFalse(result["relations"]["private_related"])
        self.admit("KNOWLEDGE_REVISION", self.reference_link["id"], "PUBLISH", actor="publisher")
        result = preview.read(self.edition["id"])
        self.assertEqual(len(result["relations"]["references"]), 1)
        self.assertNotIn(self.transcript_text, repr(result))
        self.assertEqual(preview.browse()["total"], 1)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        with self.assertRaises(services.PrivacyDenied):
            services.require(
                "SOURCE_VERSION", self.source_id, principal=services.public_principal()
            )

    def test_source_read_cannot_replace_publish_and_revoked_source_removes_counts(self):
        self.admit("PUBLICATION", self.edition["id"], "READ", "SEARCH", actor=None, level="PUBLIC")
        self.admit("ANSWER", self.edition_row.answer_id, "PUBLISH", actor="publisher")
        self.admit("SOURCE_VERSION", self.source_id, "READ", actor="publisher")
        self.assertEqual(preview.browse()["total"], 0)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        key = self.admit("SOURCE_VERSION", self.source_id, "PUBLISH", actor="publisher")[0]
        self.assertEqual(preview.browse()["total"], 1)
        del self.privacy.grants[key]
        self.assertEqual(preview.browse()["total"], 0)
        self.assertEqual(self.client.get(self.source_url).status_code, 404)

    def test_last_public_projection_callback_revocation_is_uniform_http_404(self):
        key = self.public_copy()[0]
        original = preview._projection

        def compose_then_revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            del self.privacy.grants[key]
            return result

        with patch.object(preview, "_projection", side_effect=compose_then_revoke):
            response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.edition_row.body.encode(), response.content)
        self.admit("SOURCE_VERSION", self.source_id, "PUBLISH", actor="publisher")
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)

    def test_private_reference_search_and_open_have_separate_current_source_grants(self):
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH")
        target = self.label("SOURCE_VERSION", self.source_id)
        self.assertEqual(citations.search_sources(**self.common)["editions"], [])
        with self.assertRaises(cases.CaseConflict):
            citations.read_source(**self.common, edition_id=self.catalog_id, source_row_id=2)
        self.permit(target, "CONFIDENTIAL", "READ")
        self.assertEqual(
            citations.read_source(**self.common, edition_id=self.catalog_id, source_row_id=2)[
                "source"
            ]["source_row_id"],
            2,
        )
        self.assertEqual(citations.search_sources(**self.common)["editions"], [])
        self.permit(target, "CONFIDENTIAL", "SEARCH")
        self.assertEqual(len(citations.search_sources(**self.common)["editions"]), 1)

    def test_publication_approval_requires_edition_and_source_publish_without_reclassifying(self):
        # The existing independently approved edition can be inspected privately
        # only after its own label; a CASE label does not reveal its body.
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH")
        self.assertEqual(publications.desk(**self.common)["editions"], [])
        self.admit("PUBLICATION", self.edition["id"], "READ")
        desk = publications.desk(**self.common)
        self.assertEqual(len(desk["editions"]), 1)
        self.assertIsNone(desk["approved"])
        self.assertEqual(preview.browse()["total"], 0)


@override_settings(**intake_http.DESK_SETTINGS)
class SourceIntakePrivacyTests(PrivacyFixture, TransactionTestCase):
    # Reuse the exact native source fixture without inheriting its unrelated tests.
    def setUp(self):
        intake_http.SourceDeskHTTPTests.setUp(self)
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.authority = Authority()
        self.target = locate("CASE", self.root["case_id"])
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True, FATWA_DATA_PRIVACY_AUTHORITY=self.authority
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def admit(self, kind, identifier, *actions):
        target = locate(kind, identifier)
        if not services.history(target):
            self.classify(target)
        return [self.allow(target, "CONFIDENTIAL", action) for action in actions]

    def test_bound_and_unbound_receipts_are_filtered_before_inbox_metadata_and_raw(self):
        self.assertEqual(desk_services.inbox(**self.common)["receipts"], [])
        self.admit("CASE", self.root["case_id"], "READ", "SEARCH")
        self.admit("SOURCE_RECEIPT", self.root["receipt_id"], "READ", "SEARCH")
        listing = desk_services.inbox(**self.common)
        self.assertEqual(
            [row["receipt_id"] for row in listing["receipts"]], [self.root["receipt_id"]]
        )
        self.assertIsNone(listing["next_page"])
        self.admit("SOURCE_RECEIPT", self.held["receipt_id"], "READ", "SEARCH")
        self.assertEqual(len(desk_services.inbox(**self.common)["receipts"]), 2)
        response = post(
            self.client,
            "/casework/staff/",
            {"action": "source_raw_view", "receipt_id": self.held["receipt_id"]},
            self.page,
        )
        self.assertEqual(response.status_code, 200)
        response = post(
            self.client,
            "/casework/staff/",
            {"action": "source_raw", "receipt_id": self.held["receipt_id"]},
            self.page,
        )
        self.assertEqual(response.status_code, 409)
        self.admit("SOURCE_RECEIPT", self.held["receipt_id"], "EXPORT")
        response = post(
            self.client,
            "/casework/staff/",
            {"action": "source_raw", "receipt_id": self.held["receipt_id"]},
            self.page,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content, intake.staff_raw(receipt_id=self.held["receipt_id"], **self.common)
        )
