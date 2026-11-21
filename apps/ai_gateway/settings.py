"""Isolated development composition. This enables no provider or permission."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS]  # noqa: F405
if "apps.ai_gateway" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.ai_gateway")
FATWA_AI_GATEWAY_ENABLED = False
FATWA_AI_CITATION_CANDIDATES_ENABLED = False
FATWA_AI_GATEWAY_AUTHORITY = None
FATWA_AI_CITATION_PROVIDER = None
FATWA_AI_DISABLED_PROVIDERS = frozenset()
