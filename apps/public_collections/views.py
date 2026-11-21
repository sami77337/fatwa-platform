"""Anonymous safe DTOs only; all assembly/rendering stays within current grants."""

from pathlib import Path

from django.http import HttpResponse
from django.shortcuts import render

from apps.casework_web.guard import enabled as question_enabled
from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read
from apps.library_preview.navigation import teaching_catalog_url

from . import services


def _query(request):
    if set(request.GET) - {"q", "kind", "topic"} or any(
        len(values) != 1 for _, values in request.GET.lists()
    ):
        raise preview.InvalidFilter()
    query, kind, topic = (
        request.GET.get("q", ""),
        request.GET.get("kind", ""),
        request.GET.get("topic", ""),
    )
    if (
        len(query) > 80
        or any(ord(char) < 32 for char in query)
        or kind not in {"", *services.KINDS}
        or len(topic) > 36
    ):
        raise preview.InvalidFilter()
    return {"q": query, "kind": kind, "topic": topic}


@safe_read
def index(request):
    filters = _query(request)
    with services.public_projection() as rows:
        topics = [row for row in rows if row["kind"] == "TOPIC"]
        filtered = rows
        if filters["kind"]:
            filtered = [row for row in filtered if row["kind"] == filters["kind"]]
        if filters["topic"]:
            descendants = {filters["topic"]}
            for _ in range(5):
                descendants.update(
                    row["id"]
                    for row in topics
                    if row["parent"] and row["parent"]["id"] in descendants
                )
            filtered = [row for row in filtered if row["id"] in descendants]
        if filters["q"].strip():
            words = filters["q"].casefold().split()
            filtered = [
                row
                for row in filtered
                if all(
                    word
                    in (
                        row["title"]
                        + " "
                        + row["introduction"]
                        + " "
                        + " ".join(member["title"] for member in row["members"])
                    ).casefold()
                    for word in words
                )
            ]
        # Home selections are deliberate reviewed memberships, not private
        # popularity, queues, hidden-item counts or an inferred scientific rank.
        groups = {"فتاوى مختارة": [], "علماء": [], "دروس": [], "المكتبة": []}
        seen = set()
        for row in filtered:
            if row["kind"] != "HOME" or not row["featured"]:
                continue
            for card in row["members"]:
                if card["url"] in seen:
                    continue
                seen.add(card["url"])
                label = {
                    "PUBLICATION": "فتاوى مختارة",
                    "PRESENTATION": "فتاوى مختارة",
                    "SCHOLAR": "علماء",
                    "LESSON": "دروس",
                    "LIBRARY": "المكتبة",
                }[card["kind"]]
                groups[label].append(card)
        return render(
            request,
            "public_collections/index.html",
            {
                "rows": filtered,
                "topics": topics,
                "filters": filters,
                "kinds": services.KINDS.items(),
                "featured_topics": [row for row in topics if row["featured"]],
                "groups": groups.items(),
                "question_enabled": question_enabled(),
                "teaching_url": teaching_catalog_url(),
            },
        )


@safe_read
def detail(request, public_id):
    if request.GET:
        raise preview.InvalidFilter()
    with services.public_projection() as rows:
        row = next((row for row in rows if row["id"] == str(public_id)), None)
        if row is None:
            raise preview.PreviewUnavailable()
        children = [item for item in rows if item["parent"] and item["parent"]["id"] == row["id"]]
        return render(
            request, "public_collections/detail.html", {"collection": row, "children": children}
        )


@safe_read
def stylesheet(request):
    if request.GET:
        raise preview.InvalidFilter()
    return HttpResponse(
        (Path(__file__).parent / "static/public_collections/collections.css").read_text(),
        content_type="text/css; charset=utf-8",
    )
