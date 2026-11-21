"""Public entry points are visible only in the explicitly enabled composition."""

from django.apps import apps
from django.conf import settings
from django.urls import NoReverseMatch, reverse


def teaching_catalog_url():
    if (
        not apps.is_installed("apps.public_teaching")
        or getattr(settings, "FATWA_PUBLIC_TEACHING_ENABLED", False) is not True
        or getattr(settings, "FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED", False) is not True
    ):
        return ""
    try:
        return reverse("teaching_catalog")
    except NoReverseMatch:
        return ""
