from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.case_organization"]))  # noqa: F405
