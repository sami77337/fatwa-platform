"""Loopback GET projections of a fixed replay, never workflow commands."""

from pathlib import Path

from django.core.exceptions import TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.editorial_workbench.services import WorkbenchDataError, build_cases
from apps.revision_core.revision_history import HistoryDataError

from .services import CASE_KEYS, build_rehearsal


def _exact(value: str) -> str:
    return mark_safe(str(escape(value)).replace("\r", "&#13;"))


def _failure(request: HttpRequest, status: int) -> HttpResponse:
    response = render(request, "workflow_rehearsal/error.html", status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def desk(request: HttpRequest, key: str | None = None) -> HttpResponse:
    local_only(request)
    try:
        query = request.GET
        step = query.get("step")
        if (
            set(query) - {"step"}
            or any(len(query.getlist(name)) != 1 for name in query)
            or (key is None and query)
            or step is not None
            and (
                not step.isascii()
                or not step.isdecimal()
                or len(step) > 2
                or str(int(step)) != step
            )
        ):
            return _failure(request, 400)
    except (ValueError, TooManyFieldsSent):
        return _failure(request, 400)
    if key is not None and key not in CASE_KEYS:
        return _failure(request, 404)
    try:
        cases = build_cases() if key is None else ()
        rehearsal = build_rehearsal(key) if key else None
    except (WorkbenchDataError, HistoryDataError):
        return _failure(request, 503)
    context = {"cases": cases, "rehearsal": rehearsal}
    if rehearsal is not None:
        selected = int(step) if step is not None else len(rehearsal.steps)
        if selected > len(rehearsal.steps):
            return _failure(request, 400)
        case = rehearsal.case
        visible = rehearsal.steps[:selected]
        record = rehearsal.source_record
        preparation = record.current.state.value if record else None
        review = "UNREVIEWED"
        revision = record.current.number if record else None
        if visible:
            preparation, review, revision = (
                visible[-1].to_preparation,
                visible[-1].to_review,
                visible[-1].to_revision,
            )
        context.update(
            selected_step=selected,
            visible_steps=visible,
            preparation=preparation,
            review=review,
            revision=revision,
            question=_exact(case.question if case.question is not None else "لم يرد نص سؤال"),
            source=_exact(case.raw_source),
            original_history=tuple(
                {
                    "revision": entry.revision,
                    "title": _exact(entry.revision.title),
                    "answer": _exact(entry.revision.answer),
                }
                for entry in rehearsal.source_audit
            ),
            audit=tuple(
                entry
                for entry in rehearsal.audit
                if revision is not None and entry.revision.number <= revision
            ),
            reference_rows=tuple(
                {"reference": ref, "source": _exact(ref["source"]["text"])}
                for ref in case.references
            ),
            previous_step=selected - 1 if selected else None,
            next_step=selected + 1 if selected < len(rehearsal.steps) else None,
        )
    response = render(request, "workflow_rehearsal/desk.html", context)
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        if request.GET:
            return _failure(request, 400)
        content = Path(__file__).with_name("rehearsal.css").read_bytes()
    except TooManyFieldsSent:
        return _failure(request, 400)
    except OSError:
        return _failure(request, 503)
    response = HttpResponse(content, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
