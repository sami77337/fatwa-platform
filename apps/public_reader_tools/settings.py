from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.public_reader_tools"]))  # noqa: F405
ROOT_URLCONF = "config.campaign_urls"
FATWA_PUBLIC_READER_TOOLS_ENABLED = False
FATWA_PUBLIC_READER_TOOLS_AUTHORITY = None
