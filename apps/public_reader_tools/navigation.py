"""Navigation to the independent current-policy public reader actions."""

from django.apps import apps
from django.conf import settings


def publication_tools_url(publication_id):
    if (
        apps.is_installed("apps.public_reader_tools")
        and getattr(settings, "FATWA_PUBLIC_READER_TOOLS_ENABLED", False) is True
    ):
        return f"/library-preview/reading/{publication_id}/"
    return ""
