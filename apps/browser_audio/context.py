"""Opt-in presentation only; existing forms still authenticate and authorize every save."""

from django.conf import settings

from apps.casework_web.guard import enabled


def capture(request):
    return {
        "audio_capture_enabled": enabled()
        and getattr(settings, "FATWA_BROWSER_AUDIO_ENABLED", False) is True
    }
