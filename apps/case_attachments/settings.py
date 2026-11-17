"""Focused synthetic test profile; canonical campaign registration belongs to integration."""

from config.settings.campaign_review import *  # noqa: F403

if not any(app.startswith("apps.case_attachments") for app in INSTALLED_APPS):  # noqa: F405
    INSTALLED_APPS = [*INSTALLED_APPS, "apps.case_attachments.apps.CaseAttachmentsConfig"]  # noqa: F405
ROOT_URLCONF = "apps.case_attachments.urls"
FATWA_CASE_ATTACHMENTS_ENABLED = False
