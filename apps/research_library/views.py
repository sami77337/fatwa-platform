"""Current public material cards, exact-version readers and separately allowed files."""

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render

from apps.casework.services import CaseConflict
from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read

from . import public, services
from .editor import LABELS


def _media(response):
    response._allow_library_media = True
    return response


@safe_read
def index(request):
    if set(request.GET) - {"q", "kind", "page"} or any(len(v) != 1 for _, v in request.GET.lists()):
        raise preview.InvalidFilter()
    query, kind = request.GET.get("q", ""), request.GET.get("kind", "")
    page = request.GET.get("page", "1")
    if (
        len(query) > 160
        or kind not in {"", *services.KINDS}
        or not page.isascii()
        or not page.isdigit()
        or not 1 <= int(page) <= 8
    ):
        raise preview.InvalidFilter()
    with public.public_projection() as snapshot:
        latest = {}
        for row in snapshot.search_records():
            if row["id"] not in latest or row["number"] > latest[row["id"]]["number"]:
                latest[row["id"]] = row
        rows = sorted(
            (
                r
                for r in latest.values()
                if (not kind or r["kind"] == kind)
                and (
                    not query
                    or query.casefold()
                    in (r["title"] + " " + r["work_title"] + " " + r["creator"]).casefold()
                )
            ),
            key=lambda r: (r["title"], r["id"]),
        )
        offset = (int(page) - 1) * 8
        return render(
            request,
            "research_library/public_index.html",
            {
                "rows": rows[offset : offset + 8],
                "query": query,
                "kind": kind,
                "kinds": LABELS,
                "page": int(page),
                "has_next": len(rows) > offset + 8,
                "previous": int(page) - 1,
                "next": int(page) + 1,
                "offline_enabled": getattr(settings, "FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED", False) is True,
                "material_api_enabled": getattr(settings, "FATWA_MATERIAL_API_ENABLED", False) is True,
            },
        )


@safe_read
def detail(request, public_id, number):
    if request.GET:
        raise preview.InvalidFilter()
    with public.public_projection() as snapshot:
        row = snapshot.locate(public_id, number)
        can_download = False
        if row["file"] and "DOWNLOAD" in row["uses"]:
            try:
                snapshot.authorize_use(row["version_id"], "DOWNLOAD")
                can_download = True
            except (CaseConflict, preview.PreviewUnavailable):
                pass
        return _media(render(request, "research_library/public_detail.html", {"material": row, "can_download": can_download}))


@safe_read
def file(request, public_id, number):
    if (
        set(request.GET) - {"download"}
        or any(len(v) != 1 for _, v in request.GET.lists())
        or request.GET.get("download", "0") not in {"0", "1"}
    ):
        raise preview.InvalidFilter()
    with public.public_projection() as snapshot:
        row = snapshot.locate(public_id, number)
        download = request.GET.get("download") == "1"
        result = snapshot.content(
            row["version_id"], usage="DOWNLOAD" if download else "PUBLIC_CONTENT"
        )
        response = HttpResponse(result["raw"], content_type=result["media_type"])
        response["Content-Disposition"] = (
            "attachment" if download else "inline"
        ) + f'; filename="{result["filename"]}"'
        response["X-Content-SHA256"] = result["sha256"]
        return response
