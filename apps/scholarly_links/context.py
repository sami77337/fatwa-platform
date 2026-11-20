from django.apps import apps
from django.conf import settings


def scholarly_links(request):
    return {
        "scholarly_links_enabled": apps.is_installed("apps.scholarly_links")
        and getattr(settings, "FATWA_SCHOLARLY_LINKS_ENABLED", False) is True
    }
