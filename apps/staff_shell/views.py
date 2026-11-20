"""Static installable staff shell. Private case responses are never cached here."""

import base64
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse

from apps.casework_web.guard import denied, private

ROOT = "/casework/staff/"
STATIC = Path(__file__).parent / "static/staff_shell"
ASSETS = {"install.mjs": "text/javascript", "sw.mjs": "text/javascript",
          "icon-192.png": "image/png", "icon-512.png": "image/png"}


def asset(request, name):
    if getattr(settings, "FATWA_STAFF_PWA_ENABLED", False) is not True:
        return denied("staff_installation_disabled", 404)
    if request.method not in {"GET", "HEAD"} or request.GET:
        return denied("staff_installation_unavailable", 404)
    if name == "manifest.webmanifest":
        response = JsonResponse({
            "id": ROOT, "name": "مكتب الشيخ — الفتاوى والمعرفة", "short_name": "مكتب الشيخ",
            "lang": "ar", "dir": "rtl", "start_url": ROOT, "scope": ROOT,
            "display": "standalone", "background_color": "#f4f6f9", "theme_color": "#12516c",
            "icons": [{"src": ROOT + "pwa/" + f"icon-{size}.png", "sizes": f"{size}x{size}",
                       "type": "image/png", "purpose": "any maskable"} for size in (192, 512)],
        }, content_type="application/manifest+json")
    elif name in ASSETS:
        source = STATIC / (name + ".b64" if name.endswith(".png") else name)
        raw = base64.b64decode(source.read_text().strip(), validate=True) if name.endswith(".png") else source.read_bytes()
        response = HttpResponse(raw, content_type=ASSETS[name])
        if name == "sw.mjs":
            response["Service-Worker-Allowed"] = ROOT
    else:
        return denied("staff_installation_unavailable", 404)
    return private(response, head=request.method == "HEAD")
