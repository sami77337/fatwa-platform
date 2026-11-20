"""Optional navigation only; the destination rechecks publication and media rights."""

from django.apps import apps
from django.conf import settings
from django.urls import reverse


def publication_recordings_url(publication_id):
    if (
        apps.is_installed("apps.public_answer_media")
        and getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED", False) is True
    ):
        return reverse("publication_recordings", args=[publication_id])
    return ""
