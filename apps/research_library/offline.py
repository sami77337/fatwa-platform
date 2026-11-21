"""Explicitly selected public copies and readable archives under current OFFLINE rights."""

import base64
import io
import json
import uuid
import zipfile
from hashlib import sha256
from html import escape
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from apps.casework.services import CaseConflict
from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read

from . import public, services

ROOT = "/library-preview/materials/offline/"
FORMAT = "fatwa-public-offline-v1"
ASSETS = {
    "index.html": "text/html; charset=utf-8",
    "app.mjs": "text/javascript; charset=utf-8",
    "core.mjs": "text/javascript; charset=utf-8",
    "sw.mjs": "text/javascript; charset=utf-8",
    "offline.css": "text/css; charset=utf-8",
    "icon.svg": "image/svg+xml",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}
TYPES = {
    "text/plain": "txt",
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "video/webm": "webm",
    "video/mp4": "mp4",
}


def _enabled():
    try:
        services.enabled()
    except CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
    if (
        getattr(settings, "FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED", False) is not True
        or getattr(settings, "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED", False) is not True
    ):
        raise preview.PreviewUnavailable()


def _clean(request):
    _enabled()
    if request.GET:
        raise preview.InvalidFilter()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def packet(snapshot, version_id):
    row = snapshot.authorize_use(version_id, "OFFLINE")
    raw = b""
    if row["file"]:
        raw = snapshot.content(version_id, usage="OFFLINE")["raw"]
        if row["file"]["media_type"] not in TYPES:
            raise preview.PreviewUnavailable()
    return {
        "format": FORMAT,
        "prepared_at": timezone.now().isoformat(),
        "expires_at": min(snapshot.deadlines).isoformat(),
        "material": {key: value for key, value in row.items() if key != "uses"},
        "file_base64": base64.b64encode(raw).decode("ascii"),
    }


@safe_read
def asset(request, name="index.html"):
    _clean(request)
    if name not in ASSETS:
        raise preview.PreviewUnavailable()
    folder = Path(__file__).parent / "static/research_library/offline"
    raw = (
        base64.b64decode((folder / (name + ".b64")).read_text().strip(), validate=True)
        if name.endswith(".png")
        else (folder / name).read_bytes()
    )
    response = HttpResponse(raw, content_type=ASSETS[name])
    response._allow_library_offline = True
    response["X-Offline-Asset"] = FORMAT
    if name == "sw.mjs":
        response["Service-Worker-Allowed"] = ROOT
    return response


@safe_read
def manifest(request):
    _clean(request)
    response = JsonResponse(
        {
            "id": ROOT,
            "name": "المواد المحفوظة للقراءة",
            "short_name": "مواد محفوظة",
            "lang": "ar",
            "dir": "rtl",
            "start_url": ROOT,
            "scope": ROOT,
            "display": "standalone",
            "background_color": "#f7f5ef",
            "theme_color": "#14584e",
            "icons": [
                {
                    "src": ROOT + "icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": ROOT + "icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": ROOT + "icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                },
            ],
        }
    )
    response["Content-Type"] = "application/manifest+json"
    response["X-Offline-Asset"] = FORMAT
    return response


@safe_read
def catalog(request):
    _clean(request)
    with public.public_projection() as snapshot:
        rows = []
        for row in snapshot.search_records():
            if "OFFLINE" in row["uses"]:
                # Current runtime grants are independent from approval history.
                try:
                    snapshot.authorize_use(row["version_id"], "OFFLINE")
                except (CaseConflict, preview.PreviewUnavailable):
                    continue
                rows.append(
                    {k: row[k] for k in ("version_id", "title", "work_title", "number", "kind")}
                )
        return JsonResponse({"format": FORMAT, "materials": rows})


@safe_read
def download_packet(request, version_id):
    _clean(request)
    with public.public_projection() as snapshot:
        raw = _json(packet(snapshot, version_id))
        response = HttpResponse(raw, content_type="application/json")
        response["X-Offline-Packet"] = FORMAT
        response["X-Content-SHA256"] = sha256(raw).hexdigest()
        return response


def _archive(packets):
    output = io.BytesIO()
    manifest_rows, body = [], []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, value in enumerate(packets, 1):
            row, file = value["material"], value["material"]["file"]
            entry = {key: val for key, val in value.items() if key != "file_base64"}
            file_path = ""
            if file:
                file_path = f"files/{index:03d}.{TYPES[file['media_type']]}"
                archive.writestr(file_path, base64.b64decode(value["file_base64"], validate=True))
            entry["archive_file"] = file_path
            manifest_rows.append(entry)
            content = f"<article><h2>{escape(row['title'])}</h2>"
            content += f"<p>{escape(row['creator'])}، {escape(row['work_title'])}، {escape(row['edition_label'])}، {escape(row['source_locator'])}. نسخة {row['number']}.</p>"
            content += f"<p>أُعدت في {escape(value['prepared_at'])}. انتهاء الإذن المسجل عند الإعداد: {escape(value['expires_at'])}.</p>"
            content += f"<p>مرجع النسخة: <code>{escape(row['url'])}</code></p>"
            if row["recorded_text"]:
                content += f"<pre>{escape(row['recorded_text'])}</pre>"
            if file:
                if row["kind"] in {"AUDIO", "VIDEO"}:
                    tag = "audio" if row["kind"] == "AUDIO" else "video"
                    content += f'<{tag} controls preload="metadata" src="{file_path}"></{tag}>'
                elif row["kind"] == "IMAGE":
                    content += f'<img src="{file_path}" alt="{escape(row["title"], quote=True)}">'
                elif file["media_type"] == "text/plain":
                    content += f"<pre>{escape(base64.b64decode(value['file_base64']).decode('utf-8'))}</pre>"
                content += f'<p><a href="{file_path}">فتح الملف الأصلي المحلي</a></p><p>SHA-256: <code>{file["sha256"]}</code></p>'
            body.append(content + "</article>")
        manifest_raw = _json(
            {"format": "fatwa-readable-offline-archive-v1", "materials": manifest_rows}
        )
        archive.writestr("manifest.json", manifest_raw)
        archive.writestr("manifest.sha256", sha256(manifest_raw).hexdigest() + "  manifest.json\n")
        archive.writestr(
            "archive.css",
            "body{font:18px system-ui;max-width:60rem;margin:2rem auto;padding:1rem;background:#f7f5ef;color:#193832}article{border-top:1px solid #789;padding:1rem 0}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}video,audio,img{max-width:100%}a{color:#12614f}",
        )
        archive.writestr(
            "index.html",
            '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'self\'; media-src \'self\'; img-src \'self\'; base-uri \'none\'"><title>أرشيف المواد المختارة</title><link rel="stylesheet" href="archive.css"><h1>أرشيف المواد المختارة</h1><p>نسخة محلية أُعدت بإذن مستقل للحفظ دون اتصال. راجع حالة المصادر عند الاتصال؛ هذا الملف المحفوظ لا يتلقى قرارات السحب اللاحقة تلقائيًا.</p><p>مواد اصطناعية للتطوير فقط.</p>'
            + "".join(body)
            + "</html>",
        )
    return output.getvalue()


@safe_read
def archive(request):
    _enabled()
    values = request.GET.getlist("version")
    if (
        set(request.GET) != {"version"}
        or not 1 <= len(values) <= 20
        or len(set(values)) != len(values)
    ):
        raise preview.InvalidFilter()
    try:
        selected = [str(uuid.UUID(value)) for value in values]
    except (ValueError, TypeError) as exc:
        raise preview.InvalidFilter() from exc
    with public.public_projection() as snapshot:
        raw = _archive([packet(snapshot, value) for value in selected])
        response = HttpResponse(raw, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="offline-materials.zip"'
        response["X-Content-SHA256"] = sha256(raw).hexdigest()
        return response
