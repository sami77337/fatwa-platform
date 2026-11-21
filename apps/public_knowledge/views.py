"""Anonymous pages reveal only the exact current, separately released display fields."""

from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read
from apps.library_preview.navigation import teaching_catalog_url
from apps.public_answer_media.navigation import publication_recordings_url
from apps.public_reader_tools.navigation import publication_tools_url

from . import public, services


def _origin():
    value = getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_ORIGIN", "")
    if type(value) is not str or len(value) > 300:
        return ""
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            return ""
        if any(character.isspace() or ord(character) < 33 for character in value):
            return ""
        parts.port
        return f"https://{parts.netloc}"
    except ValueError:
        return ""


def _url(name, *args):
    return reverse("public_knowledge:" + name, args=args)


def _decorate(snapshot):
    for row in snapshot.scholars.values():
        row["url"] = _url("scholar", row["id"])
    for row in snapshot.topics.values():
        row["url"] = _url("topic", row["id"])
    for row in snapshot.presentations.values():
        row["url"] = _url("publication", row["publication_id"], row["language"])
    for row in snapshot.lessons.values():
        row["url"] = _url("lesson", row["id"])


def _cards(rows):
    for row in rows:
        row["url"] = _url("publication", row["publication_id"], "ar")
    return rows


def _page(request, template, snapshot, *, title, path, crumbs=(), description="", **context):
    breadcrumbs = [
        {"title": "المكتبة", "url": reverse("library_preview:index")},
        {"title": "العلماء والموضوعات", "url": _url("index")},
        *crumbs,
    ]
    for position, row in enumerate(breadcrumbs, 1):
        row["position"] = position
    return render(
        request,
        template,
        {
            "title": title,
            "description": description,
            "canonical": _origin() + path if _origin() else "",
            "breadcrumbs": breadcrumbs,
            "teaching_url": teaching_catalog_url(),
            **context,
        },
    )


def _query(request):
    if request.GET:
        raise preview.InvalidFilter()


@safe_read
def index(request):
    _query(request)
    with public.projection() as snapshot:
        _decorate(snapshot)
        return _page(
            request,
            "public_knowledge/index.html",
            snapshot,
            title="العلماء والموضوعات والمواد",
            path=_url("index"),
            scholars=sorted(snapshot.scholars.values(), key=lambda row: row["name"]),
            topics=sorted(
                (row for row in snapshot.topics.values() if row["parent"] is None),
                key=lambda row: row["title"],
            ),
            publications=_cards(snapshot.publication_cards()),
            lessons=list(snapshot.lessons.values()),
        )


@safe_read
def scholar(request, series_id):
    _query(request)
    with public.projection() as snapshot:
        _decorate(snapshot)
        row = snapshot.scholar(series_id)
        _cards(row["publications"])
        return _page(
            request,
            "public_knowledge/scholar.html",
            snapshot,
            title=row["name"],
            description=row["bio"][:320],
            path=_url("scholar", series_id),
            crumbs=[{"title": row["name"], "url": row["url"]}],
            scholar=row,
        )


def _topic_crumbs(row):
    result, current = [], row
    while current:
        if len(result) >= 5:
            raise preview.PreviewUnavailable()
        result.append({"title": current["title"], "url": current["url"]})
        current = current["parent"]
    return list(reversed(result))


@safe_read
def topic(request, series_id):
    _query(request)
    with public.projection() as snapshot:
        _decorate(snapshot)
        row = snapshot.topic(series_id)
        _cards(row["publications"])
        for reference in row["references"]:
            reference["url"] = reverse(
                "library_preview:source", args=[reference["publication_id"], reference["position"]]
            )
        return _page(
            request,
            "public_knowledge/topic.html",
            snapshot,
            title=row["title"],
            description=row["introduction"][:320],
            path=_url("topic", series_id),
            crumbs=_topic_crumbs(row),
            topic=row,
        )


@safe_read
def lesson(request, series_id):
    _query(request)
    with public.projection() as snapshot:
        _decorate(snapshot)
        row = snapshot.lesson(series_id)
        return _page(
            request,
            "public_knowledge/lesson.html",
            snapshot,
            title=row["title"],
            description=row["summary"][:320],
            path=_url("lesson", series_id),
            crumbs=[{"title": row["title"], "url": row["url"]}],
            lesson=row,
        )


@safe_read
def publication_page(request, publication_id, language="ar"):
    _query(request)
    if language not in services.languages():
        raise preview.InvalidFilter()
    with public.projection() as snapshot:
        _decorate(snapshot)
        source = snapshot.sources.get(str(publication_id))
        if source is None:
            raise preview.PreviewUnavailable()
        edition, values = source
        selected = snapshot.presentation(publication_id, language)
        missing = selected is None and language != "ar"
        row = (
            selected
            or snapshot.presentation(publication_id, "ar")
            or {
                "title": values["title"],
                "body": values["body"],
                "question": "",
                "description": "",
                "language": "ar",
                "version": None,
                "scholar": None,
                "topics": [],
                "references": values["references"],
                "source_version": values["number"],
            }
        )
        row = dict(row)
        for reference in row["references"]:
            reference["url"] = reverse(
                "library_preview:source", args=[publication_id, reference["position"]]
            )
        related = row.get("related", [])
        for target in related:
            if target["publication_id"] not in snapshot.sources:
                raise preview.PreviewUnavailable()
            target["title"] = snapshot.sources[target["publication_id"]][1]["title"]
            target["url"] = _url("publication", target["publication_id"], "ar")
        lessons = [
            item
            for item in snapshot.lessons.values()
            if item["publication_id"] == str(publication_id)
        ]
        available = []
        for code, label in services.languages().items():
            translation = snapshot.presentation(publication_id, code)
            available.append(
                {
                    "code": code,
                    "label": label,
                    "available": code == "ar" or translation is not None,
                    "url": _url("publication", publication_id, code),
                }
            )
        original_url = _url("publication", publication_id, "ar")
        path = _url("publication", publication_id, row["language"])
        crumbs = _topic_crumbs(row["topics"][0]) if row["topics"] else []
        crumbs.append({"title": row["title"], "url": path})
        return _page(
            request,
            "public_knowledge/publication.html",
            snapshot,
            title=row["title"],
            description=row["description"],
            path=path,
            crumbs=crumbs,
            edition=row,
            languages=available,
            missing_translation=missing,
            original_url=original_url,
            recordings_url=publication_recordings_url(publication_id),
            reader_tools_url=publication_tools_url(publication_id),
            original_canonical=_origin() + original_url if _origin() else "",
            related=related,
            lessons=lessons,
            published_at=edition.actions.get(action="APPROVE").created_at,
        )


@safe_read
def sitemap(request):
    _query(request)
    origin = _origin()
    if not origin:
        raise preview.PreviewUnavailable()
    with public.projection() as snapshot:
        _decorate(snapshot)
        urls = {_url("index"): None}
        for row in snapshot.scholars.values():
            urls[row["url"]] = row["updated_at"]
        for row in snapshot.topics.values():
            urls[row["url"]] = row["updated_at"]
        for row in snapshot.lessons.values():
            urls[row["url"]] = row["updated_at"]
        for identifier, (source, _) in snapshot.sources.items():
            urls[_url("publication", identifier, "ar")] = source.actions.get(
                action="APPROVE"
            ).created_at
        for row in snapshot.presentations.values():
            urls[row["url"]] = row["updated_at"]
        if len(urls) > 512:
            raise preview.PreviewUnavailable()
        root = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
        for path, changed in sorted(urls.items()):
            item = SubElement(root, "url")
            SubElement(item, "loc").text = origin + path
            if changed is not None:
                SubElement(item, "lastmod").text = changed.isoformat()
        return HttpResponse(
            tostring(root, encoding="utf-8", xml_declaration=True),
            content_type="application/xml; charset=utf-8",
        )
