"""Optional development composition; production policies are never installed here."""

from config.settings import campaign_review as base
from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(
    dict.fromkeys([*base.INSTALLED_APPS, "apps.research_library", "apps.material_import"])
)
ROOT_URLCONF = "config.campaign_urls"
FATWA_MATERIAL_IMPORT_ENABLED = False
FATWA_MATERIAL_IMPORT_AUTHORITY = None
FATWA_MATERIAL_IMPORT_TTL_SECONDS = 1800
DATA_UPLOAD_MAX_NUMBER_FIELDS = 32
