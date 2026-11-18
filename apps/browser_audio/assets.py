"""Fixed local assets only; shared route admission is the integrator's responsibility."""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.urls import path

from apps.casework_web.guard import denied, enabled, private

ROOT = Path(__file__).parent / "static" / "browser_audio"
ASSETS = {
    "capture.js": "text/javascript",
    "worklet.js": "text/javascript",
    "capture.css": "text/css",
}


def asset(request, filename):
    if (
        not enabled()
        or getattr(settings, "FATWA_BROWSER_AUDIO_ENABLED", False) is not True
        or filename not in ASSETS
        or request.method not in {"GET", "HEAD"}
        or request.GET
    ):
        return denied("browser_audio_unavailable", 404)
    return private(
        HttpResponse((ROOT / filename).read_bytes(), content_type=ASSETS[filename]),
        head=request.method == "HEAD",
    )


urlpatterns = [path(f"casework/audio-{name}", asset, {"filename": name}) for name in ASSETS]
ASSET_ROUTES = {"/" + str(pattern.pattern): ("GET", "HEAD") for pattern in urlpatterns}
