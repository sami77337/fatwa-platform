"""Two actual roles using the unchanged campaign routes and closed policies."""

from django.test import override_settings

from apps.case_attachments.tests import new_case
from apps.operational_workspace.test_support import Authority as OperationalAuthority
from apps.operational_workspace.test_support import Directory
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .catalog import LEVELS, locate
from .test_management import ManagementFixture
from .test_support import Authority, PrivacyFixture

FEATURES = {
    key: value
    for key, value in WEB_SETTINGS.items()
    if key not in {"MIDDLEWARE", "ROOT_URLCONF", "DATA_UPLOAD_MAX_NUMBER_FIELDS"}
}
FEATURES.update(
    ROOT_URLCONF="config.campaign_urls",
    FATWA_OPERATIONAL_WORKSPACE_ENABLED=True,
)


class CampaignFixture:
    allow = PrivacyFixture.allow
    source_rows = staticmethod(ManagementFixture.source_rows)

    def setUp(self):
        super().setUp()
        self.receipt = new_case()
        self.originals = self.source_rows()
        self.directory = Directory([self.receipt["public_ref"]])
        self.authority = Authority()
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=OperationalAuthority({"case": self.receipt}),
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.target = locate("CASE", self.receipt["case_id"])
        for subject in ("mufti", "admin"):
            principal = self.principal(subject)
            for level in ("", *LEVELS):
                self.allow(self.target, level, "VIEW_CLASSIFICATION", principal=principal)
            previous = ""
            for level in LEVELS:
                self.allow(
                    self.target, level, "CLASSIFY", previous_level=previous, principal=principal
                )
                previous = level
        self.allow(
            self.target,
            "CONFIDENTIAL",
            "CLASSIFY",
            previous_level="RESTRICTED",
            principal=self.principal("admin"),
        )

    def principal(self, subject="mufti"):
        return services.staff_principal(self.directory, self.directory.resolve(subject))
