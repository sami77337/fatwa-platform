"""Library edition links return to the existing scoped current-case frame."""

from django.test import TransactionTestCase, override_settings

from apps.experimental_publication import tests_ui as fixtures
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
        "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    }
)
class PublicationFrameTests(TransactionTestCase):
    setUp = fixtures.PublicationContinuityTests.setUp
    edition = fixtures.PublicationContinuityTests.edition
    login = fixtures.PublicationContinuityTests.login

    def test_authorized_edition_resolution_restores_frame_without_browser_case_grant(self):
        edition = self.edition()
        client, page = self.login()
        page = post(
            client, "/casework/staff/", {"action": "pub_open", "edition_id": edition["id"]}, page
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="mufti-case-reference"')
        self.assertEqual(
            page.context["mufti_workspace"]["case"]["case_id"], self.receipt["case_id"]
        )
        self.assertEqual(page.context["mufti_workspace"]["active"], "publication")
        response = post(
            client,
            "/casework/staff/",
            {
                "action": "pub_open",
                "edition_id": edition["id"],
                "publication_authorized_case_ref": self.receipt["public_ref"],
            },
            page,
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, 'id="mufti-case-reference"', status_code=400)
