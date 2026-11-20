"""Isolated synthetic composition; no publishing or curation permission by default."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(
    dict.fromkeys([*INSTALLED_APPS, "apps.scholarly_links", "apps.public_knowledge"])  # noqa: F405
)
FATWA_SCHOLARLY_LINKS_ENABLED = False
FATWA_SCHOLARLY_LINKS_AUTHORITY = None
FATWA_PUBLIC_KNOWLEDGE_ENABLED = False
FATWA_PUBLIC_KNOWLEDGE_AUTHORITY = None
FATWA_PUBLIC_KNOWLEDGE_LANGUAGES = {"ar": "العربية"}
FATWA_PUBLIC_KNOWLEDGE_ORIGIN = ""
ROOT_URLCONF = "apps.public_knowledge.urls"
