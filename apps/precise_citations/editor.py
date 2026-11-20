"""CSRF-bound native composer; source actions retain the literal unsaved answer."""

import json
import uuid

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_safe

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import services, sources
from .boundary import digest, scope
from .models import CitationAnchor, CitationSet

ACTIONS = frozenset({"precise_open", "precise_compose", "precise_review", "precise_revision"})
FIELDS = {
    "action",
    "case_ref",
    "csrfmiddlewaretoken",
    "state",
    "text",
    "phrase",
    "occurrence",
    "selection",
    "mode",
    "start",
    "end",
    "label",
    "limitation",
    "part_id",
    "title",
    "edition",
    "location",
    "url",
    "command",
    "index",
    "confirmed",
    "set_id",
    "note",
    "decision",
    "previous_id",
    "correction_reason",
}


def number(value):
    if type(value) is not str or not value.isascii() or not value.isdecimal() or len(value) > 9:
        raise cases.CaseConflict("precise_citation_number_invalid")
    return int(value)


def principal(request):
    provider = _provider()
    actor = current_staff(request, provider)
    return actor, RequestDirectory(provider, actor, authenticated_provider_id=provider.provider_id)


def binding(request, actor, provider, case):
    get_token(request)
    return digest(
        [
            str(case.pk),
            provider.provider_id,
            actor.subject_id,
            actor.auth_epoch,
            request.META.get("CSRF_COOKIE", ""),
        ]
    )


def seal_state(state, audience):
    return signing.dumps(
        {**state, "audience": audience}, salt="precise-citation-composer.v1", compress=True
    )


def open_state(value, audience):
    if type(value) is not str or len(value) > 64000:
        raise cases.CaseConflict("precise_citation_draft_invalid")
    try:
        state = signing.loads(value, salt="precise-citation-composer.v1", max_age=600)
    except signing.BadSignature as exc:
        raise cases.CaseConflict("precise_citation_draft_expired") from exc
    if state.get("audience") != audience:
        raise cases.CaseConflict("precise_citation_draft_audience")
    return state


def page(
    request,
    base,
    actor,
    provider,
    *,
    state=None,
    text=None,
    phrase="",
    preview=None,
    occurrences=None,
    selected_id=None,
    message="",
    form=None,
):
    with scope(**base) as guard:
        selected = services.current(guard, base["case_id"])
        case = guard.locked[cases._uuid(base["case_id"])]
        audience = binding(request, actor, provider, case)
        choices = sources.choices(guard, case.pk)
        row = CitationSet.objects.filter(answer__case=case).order_by("-answer__revision").first()
        if selected_id:
            row = CitationSet.objects.filter(pk=cases._uuid(selected_id), answer__case=case).first()
            if row is None:
                raise cases.CaseConflict("precise_citation_set_unavailable")
        record = services.read_locked(guard, case_id=case.pk, set_id=row.pk) if row else None
        if state is None:
            state = {
                "revision": selected["revision"],
                "evidence_version": selected["evidence_version"],
                "request_key": str(uuid.uuid4()),
                "entries": [],
            }
        if text is None:
            text = selected["answers"][-1]["text"] if selected["answers"] else ""
        # Revalidate every pending source before it appears, with no saved access
        # grants in the browser token. An edited phrase must be selected again.
        pending = []
        for entry in state["entries"]:
            services.anchor(text, **entry)
            live = sources.read(guard, entry["source"], owner_case_id=case.pk)
            pending.append({**entry, "reference": live["reference"]})
        if preview is not None:
            preview = sources.read(guard, preview, owner_case_id=case.pk)
        history = list(
            CitationSet.objects.filter(answer__case=case)
            .order_by("answer__revision")
            .values("id", "answer__revision", "subject_id", "created_at")
        )
        return private(
            render(
                request,
                "precise_citations/editor.html",
                {
                    "selected": selected,
                    "record": record,
                    "history": history,
                    "state": seal_state(state, audience),
                    "text": text,
                    "phrase": phrase,
                    "choices": choices,
                    "pending": pending,
                    "occurrences": occurrences or [],
                    "preview": preview,
                    "message": message,
                    "form": form or {},
                    "current_actor": actor.subject_id,
                },
            )
        )


@mutation_service
@sensitive_post_parameters("text", "state", "phrase", "note")
@csrf_protect
def workspace(request):
    try:
        if request.method != "POST" or request.POST.get("action") not in ACTIONS or request.FILES:
            raise InvalidForm("precise_citation_action_invalid")
        if set(request.POST) - FIELDS or any(
            len(values) != 1 for _, values in request.POST.lists()
        ):
            raise InvalidForm("precise_citation_form_invalid")
        actor, provider = principal(request)
        case = Case.objects.filter(
            public_ref=request.POST.get("case_ref"), public_ref__in=actor.case_keys
        ).first()
        if case is None:
            return denied("precise_citation_case_unavailable", 404)
        base = dict(
            case_id=case.pk,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        with synthetic_queue_atomic():
            if request.POST["action"] == "precise_open":
                return page(request, base, actor, provider)
            if request.POST["action"] == "precise_revision":
                return page(request, base, actor, provider, selected_id=request.POST.get("set_id"))
            state = open_state(
                request.POST.get("state", ""), binding(request, actor, provider, case)
            )
            if request.POST["action"] == "precise_review":
                row = services.review(
                    **base,
                    set_id=request.POST.get("set_id"),
                    action=request.POST.get("decision"),
                    note=request.POST.get("note", ""),
                    confirmed=request.POST.get("confirmed") == "yes",
                    expected_revision=state["revision"],
                    expected_evidence_version=state["evidence_version"],
                    request_key=state["request_key"],
                )
                return page(
                    request,
                    base,
                    actor,
                    provider,
                    selected_id=row["id"],
                    message="حُفظت المراجعة المستقلة؛ اعتماد الجواب إجراء منفصل.",
                )
            text = request.POST.get("text", "")
            cases._text(text)
            phrase = request.POST.get("phrase", "")
            command = request.POST.get("command")
            preview = None
            found = services.occurrences(text, phrase) if phrase else []
            with scope(**base) as guard:
                if command in {"preview", "add"}:
                    descriptor = dict(
                        title=request.POST.get("title", ""),
                        edition=request.POST.get("edition", ""),
                        location=request.POST.get("location", ""),
                        url=request.POST.get("url", ""),
                        limitation=request.POST.get("limitation", ""),
                    )
                    at = sources.locator(
                        mode=request.POST.get("mode", "METADATA"),
                        start=number(request.POST.get("start", "0")),
                        end=number(request.POST.get("end", "0")),
                        label=request.POST.get("label", ""),
                        limitation=request.POST.get("limitation", ""),
                    )
                    pin, _ = sources.select(
                        guard,
                        request.POST.get("selection", ""),
                        owner_case_id=case.pk,
                        location=at,
                        part_id=request.POST.get("part_id", ""),
                        descriptor=descriptor,
                    )
                    preview = pin
                    if command == "add":
                        start = number(request.POST.get("occurrence", ""))
                        if len(state["entries"]) >= services.MAX_ANCHORS:
                            raise cases.CaseConflict("precise_citation_selection_bound")
                        state["entries"].append(
                            services.anchor(
                                text,
                                start=start,
                                end=start + len(phrase),
                                phrase=phrase,
                                source=pin,
                                previous_id=request.POST.get("previous_id", ""),
                                correction_reason=request.POST.get("correction_reason", ""),
                            )
                        )
                elif command in {"remove", "up", "down"}:
                    index = number(request.POST.get("index", ""))
                    if index >= len(state["entries"]):
                        raise cases.CaseConflict("precise_citation_selection_invalid")
                    if command == "remove":
                        state["entries"].pop(index)
                    else:
                        destination = index + (-1 if command == "up" else 1)
                        if not 0 <= destination < len(state["entries"]):
                            raise cases.CaseConflict("precise_citation_selection_invalid")
                        state["entries"][index], state["entries"][destination] = (
                            state["entries"][destination],
                            state["entries"][index],
                        )
                elif command == "save":
                    row = services.save(
                        **base,
                        text=text,
                        selections=state["entries"],
                        expected_revision=state["revision"],
                        expected_evidence_version=state["evidence_version"],
                        request_key=state["request_key"],
                        confirmed=request.POST.get("confirmed") == "yes",
                    )
                    guard.written(case.pk)
                    return page(
                        request,
                        base,
                        actor,
                        provider,
                        selected_id=row["id"],
                        message="حُفظ إصدار جواب جديد؛ الإحالات بحاجة إلى مراجعة مستقلة.",
                    )
                elif command != "find":
                    raise cases.CaseConflict("precise_citation_command_invalid")
                return page(
                    request,
                    base,
                    actor,
                    provider,
                    state=state,
                    text=text,
                    phrase=phrase,
                    occurrences=found,
                    preview=preview,
                    form=request.POST,
                )
    except (
        cases.CaseConflict,
        InvalidForm,
        IdentityUnavailable,
        signing.BadSignature,
        SyntheticWriteDenied,
        DatabaseError,
        SuspiciousOperation,
        ValueError,
        TypeError,
        KeyError,
    ):
        return denied("precise_citation_operation_unavailable", 409)


@mutation_service
@require_safe
def source(request, anchor_id, raw=False):
    try:
        actor, provider = principal(request)
        row = (
            CitationAnchor.objects.select_related("citation_set__answer__case")
            .filter(pk=anchor_id)
            .first()
        )
        if row is None:
            return denied("precise_citation_source_unavailable", 404)
        base = dict(
            case_id=row.citation_set.answer.case_id,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        with scope(**base) as guard:
            services.read_locked(guard, case_id=base["case_id"], set_id=row.citation_set_id)
            live = sources.read(guard, row.source, owner_case_id=base["case_id"])
            if raw:
                if not live["raw"] or not live["file"]:
                    return denied("precise_citation_file_unavailable", 404)
                response = HttpResponse(live["raw"], content_type=live["file"]["media_type"])
                response["Content-Disposition"] = "inline; filename=source"
                return private(response)
            return private(
                render(request, "precise_citations/source.html", {"source": live, "anchor": row})
            )
    except (
        cases.CaseConflict,
        IdentityUnavailable,
        SyntheticWriteDenied,
        DatabaseError,
        ValueError,
    ):
        return denied("precise_citation_source_unavailable", 404)


@mutation_service
@require_safe
def export(request, set_id, format="html"):
    try:
        actor, provider = principal(request)
        row = CitationSet.objects.select_related("answer").filter(pk=set_id).first()
        if row is None:
            return denied("precise_citation_export_unavailable", 404)
        base = dict(
            case_id=row.answer.case_id,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        with scope(**base) as guard:
            data = services.read_locked(
                guard, case_id=base["case_id"], set_id=row.pk, usage="EXPORT", require_review=True
            )
            if format == "json":
                safe = {
                    "format": "human-citations.v1",
                    "answer_revision": data["answer_revision"],
                    "answer_text": data["answer_text"],
                    "citations": [
                        {
                            key: entry[key]
                            for key in (
                                "ordinal",
                                "start",
                                "end",
                                "phrase",
                                "reference",
                                "limitation",
                            )
                        }
                        for entry in data["entries"]
                    ],
                }
                response = HttpResponse(
                    json.dumps(safe, ensure_ascii=False, indent=2).encode(),
                    content_type="application/json; charset=utf-8",
                )
                response["Content-Disposition"] = 'attachment; filename="citations.json"'
            else:
                response = render(request, "precise_citations/print.html", {"record": data})
            return private(response)
    except (
        cases.CaseConflict,
        IdentityUnavailable,
        SyntheticWriteDenied,
        DatabaseError,
        ValueError,
    ):
        return denied("precise_citation_export_unavailable", 404)
