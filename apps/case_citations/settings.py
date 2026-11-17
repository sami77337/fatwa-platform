from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if not any(app.startswith("apps.case_citations") for app in INSTALLED_APPS):
    INSTALLED_APPS.append("apps.case_citations")
FATWA_CASE_CITATIONS_ENABLED = True
