"""Independent source-publication interaction probes; canonical historical fixture only."""

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.source_rights import services as rights
from apps.source_rights.tests import ENABLED, RightsFixture
from tests.casework.test_http import WEB_SETTINGS


@override_settings(
    **{**ENABLED, "FATWA_LIBRARY_PREVIEW_ENABLED": True, "FATWA_SOURCE_RIGHTS_ENFORCED": False}
)
class RightsP0Tests(RightsFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        row = PublicationEdition.objects.get(pk=self.edition["id"])
        self.policy = PreviewPolicy(
            (PublicationGrant(str(row.pk), row.content_sha256),),
            (ReferenceGrant(self.catalog_id, 2, row.citations[0]["source_sha256"]),),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        overlay = override_settings(
            FATWA_SOURCE_RIGHTS_ENFORCED=True, FATWA_LIBRARY_PREVIEW_POLICY=self.policy
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        proposal = rights.propose(
            **self.common,
            source_id=self.source["id"],
            expected_number=0,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="synthetic independent review",
            note="synthetic",
            ttl_minutes=1,
        )
        self.decision(proposal)
        self.rights_revision = proposal

    def test_revocation_closes_http_body_source_metadata_and_search_counts(self):
        self.assertEqual(preview.browse()["total"], 1)
        self.decision(self.rights_revision, "REVOKE")
        options = {
            **WEB_SETTINGS,
            "ROOT_URLCONF": "config.campaign_urls",
            "MIDDLEWARE": [
                "apps.platform_recovery.middleware.MaintenanceGuard",
                "apps.library_preview.guard.PreviewCompositionGuard",
                "django.middleware.csrf.CsrfViewMiddleware",
            ],
        }
        with override_settings(**options):
            client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
            for method in (client.get, client.head):
                for path in (
                    f"/library-preview/editions/{self.edition['id']}/",
                    f"/library-preview/editions/{self.edition['id']}/references/1/",
                ):
                    response = method(path)
                    self.assertEqual(response.status_code, 404)
                    self.assertIn("no-store", response["Cache-Control"])
                    for secret in (
                        "نص محرر مسموح",
                        self.heading.title_original,
                        self.receipt["public_ref"],
                        self.transcript_text,
                    ):
                        self.assertNotIn(secret, response.content.decode())
        self.assertEqual(preview.browse()["total"], 0)
        self.assertEqual(
            publications.library(**{k: v for k, v in self.common.items() if k != "case_id"}), []
        )

    def test_expiry_between_validation_and_projection_cannot_return_publication(self):
        original = preview._projection
        clock = [timezone.now()]
        future = clock[0] + timedelta(minutes=2)

        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            # Monotonic test clock: once source/body metadata has been assembled,
            # rights expire and remain expired through the final response checks.
            clock[0] = future
            return result

        with (
            patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
            patch.object(preview, "_projection", side_effect=delayed),
        ):
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(self.edition["id"])

    def test_source_grant_never_substitutes_independent_preview_policy(self):
        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=None):
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(self.edition["id"])
        with override_settings(FATWA_SOURCE_RIGHTS_AUTHORITY=None):
            self.assertEqual(preview.browse()["total"], 0)
