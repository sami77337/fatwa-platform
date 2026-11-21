"""Versioned public contract over the actual current library projection."""

from contextlib import contextmanager
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from apps.casework.services import CaseConflict
from apps.editorial_search.query_terms import normalize_editorial_search
from apps.library_preview import services as preview
from apps.research_library import public
from apps.research_library import services as library

SCHEMA = "fatwa.allowed-materials.v1"
MAX_LIMIT = 20


def enabled():
    if getattr(settings, "FATWA_MATERIAL_API_ENABLED", False) is not True:
        raise preview.PreviewUnavailable()


@contextmanager
def projection():
    enabled()
    identity = library.identity_snapshot(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None))
    with public.public_projection() as snapshot:
        yield snapshot
        enabled()
    # Pure checks after every permission/storage callback prevent a late read
    # from revoking identity or changing API configuration before bytes leave.
    enabled()
    if library.identity_snapshot(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)) != identity:
        raise preview.PreviewUnavailable()


def query_params(query):
    if set(query) - {"q", "kind", "page", "limit"} or any(len(v) != 1 for _, v in query.lists()):
        raise preview.InvalidFilter()
    text, kind = query.get("q", ""), query.get("kind", "")
    values = {}
    for name, default, maximum in (("page", "1", 1000), ("limit", "10", MAX_LIMIT)):
        raw = query.get(name, default)
        if not raw.isascii() or not raw.isdigit() or len(raw) > 4 or not 1 <= int(raw) <= maximum:
            raise preview.InvalidFilter()
        values[name] = int(raw)
    if len(text) > 120 or any(ord(c) < 32 for c in text) or kind not in {"", *library.KINDS}:
        raise preview.InvalidFilter()
    return {"q": text, "kind": kind, **values}


def reference(row):
    return {
        "material_id": row["id"], "version": row["number"], "version_sha256": row["digest"],
        "work_title": row["work_title"], "edition": row["edition_label"],
        "creator": row["creator"], "locator": row["source_locator"], "canonical_url": row["url"],
    }


def record(snapshot, row):
    kwargs = {"public_id": row["id"], "number": row["number"]}
    download = None
    if row["file"] and "DOWNLOAD" in row["uses"]:
        try:
            snapshot.authorize_use(row["version_id"], "DOWNLOAD")
        except (CaseConflict, preview.PreviewUnavailable):
            pass
        else:
            download = reverse("material_api:original", kwargs=kwargs)
    # Explicit field allowlist: no internal case/source/version UUID, storage
    # key, original private filename, provenance note or release actor escapes.
    return {
        "material_id": row["id"], "version": row["number"], "version_sha256": row["digest"],
        "kind": row["kind"], "title": row["title"], "description": row["description"],
        "language": row["language"], "reference": reference(row),
        "recorded_text": row["recorded_text"],
        "file": {key: row["file"][key] for key in ("media_type", "size", "sha256")} if row["file"] else None,
        "links": {"self": reverse("material_api:detail", kwargs=kwargs),
                  "canonical": row["url"], "original": download},
    }


def catalogue(snapshot, params):
    latest = {}
    for row in snapshot.search_records():
        if row["id"] not in latest or row["number"] > latest[row["id"]]["number"]:
            latest[row["id"]] = row
    normalized = normalize_editorial_search(params["q"])
    selected = sorted((row for row in latest.values()
        if (not params["kind"] or row["kind"] == params["kind"])
        and (not normalized or normalized in normalize_editorial_search(
            " ".join(row[k] for k in ("title", "work_title", "creator", "description"))
        ))), key=lambda row: (row["title"], row["id"]))
    start = (params["page"] - 1) * params["limit"]
    total = len(selected)
    def link(page):
        return reverse("material_api:index") + "?" + urlencode({**params, "page": page})
    return {
        "schema": SCHEMA,
        "query": params,
        "pagination": {"page": params["page"], "limit": params["limit"], "total": total,
                       "next": link(params["page"] + 1) if start + params["limit"] < total and params["page"] < 1000 else None,
                       "previous": link(params["page"] - 1) if params["page"] > 1 else None},
        "results": [record(snapshot, row) for row in selected[start:start + params["limit"]]],
    }
