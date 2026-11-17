from config.settings.casework_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.team_updates.apps.TeamUpdatesConfig"]  # noqa: F405
ROOT_URLCONF = "apps.team_updates.urls"
