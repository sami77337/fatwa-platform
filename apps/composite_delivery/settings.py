"""Owned test composition only; campaign registration belongs to the integrator."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.composite_delivery"]  # noqa: F405
FATWA_COMPOSITE_DELIVERY_ENABLED = False
FATWA_COMPOSITE_DELIVERY_CAPABILITIES = None
