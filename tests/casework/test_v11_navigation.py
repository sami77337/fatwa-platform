"""Integrated native denials do not re-enter the private current-case frame."""

from django.test import TransactionTestCase, override_settings

from apps.mufti_workspace import tests as workspace_fixtures
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from tests.casework.test_http import post


@override_settings(
    FATWA_MUFTI_WORKSPACE_ENABLED=True,
    FATWA_RESEARCH_WORKSPACE_ENABLED=True,
    FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
)
class ConnectedResearchDenialTests(TransactionTestCase):
    setUp = workspace_fixtures.MuftiWorkspaceTests.setUp

    def test_revoked_identity_and_foreign_case_render_denial_without_retrying_frame(self):
        foreign = workspace_fixtures.new_case("FOREIGN PRIVATE QUESTION")
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "research_open", "case_ref": foreign["public_ref"]},
            self.queue,
        )
        self.assertEqual(page.status_code, 403)
        self.assertNotContains(page, "FOREIGN PRIVATE QUESTION", status_code=403)
        self.assertNotContains(page, 'id="mufti-case-reference"', status_code=403)
        self.directory.current = None
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "research_open", "case_ref": self.receipt["public_ref"]},
            self.queue,
        )
        self.assertEqual(page.status_code, 403)
        self.assertNotContains(page, 'id="mufti-case-reference"', status_code=403)
