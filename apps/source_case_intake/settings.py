"""Local synthetic service profile; registers no inbound HTTP endpoint."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.source_case_intake"]  # noqa: F405
FATWA_SOURCE_CASE_INTAKE_ENABLED = False
