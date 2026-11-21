"""Native operational login, filters and scoped details with checks after rendering."""

import re

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework.services import CaseConflict
from apps.casework_web.guard import private
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.platform_recovery.integration import MaintenanceUnavailable

from . import (
    access,
    coordination_views,
    identity,
    lesson_links,
    metadata,
    notes,
    services,
    transcripts,
)
from . import publication as publication_manager
from .boundary import policy

BASE = access.BASE


def denied(status=409):
    return private(
        HttpResponse(
            "مساحة التشغيل غير متاحة لهذا الطلب",
            status=status,
            content_type="text/plain; charset=utf-8",
        )
    )


def boundary(request, methods):
    try:
        policy()
    except CaseConflict:
        return denied(404)
    if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
        return denied(403)
    try:
        host = request.get_host()
    except DisallowedHost:
        return denied(400)
    if re.fullmatch(r"(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", host) is None or any(
        name in request.META
        for name in ("HTTP_FORWARDED", "HTTP_X_FORWARDED_HOST", "HTTP_X_FORWARDED_FOR")
    ):
        return denied(403)
    if request.method not in methods:
        response = denied(405)
        response["Allow"] = ", ".join(methods)
        return response
    if request.GET or request.META.get("QUERY_STRING"):
        return denied(400)
    return None


def form(request, fields, *, multiple=()):
    if (
        request.FILES
        or set(request.POST) - fields - {"csrfmiddlewaretoken"}
        or any(len(request.POST.getlist(key)) != 1 for key in request.POST if key not in multiple)
    ):
        raise CaseConflict("operational_form_invalid")


def integer(request, name):
    value = request.POST.get(name)
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]{0,8}", value) is None:
        raise CaseConflict("operational_form_invalid")
    return int(value)


def optional_integer(request, name):
    return None if request.POST.get(name) in (None, "") else integer(request, name)


def transcript_segments(request):
    text, result = request.POST.get("text", ""), []
    for index in range(6):
        quote, start, end = (
            request.POST.get(f"{name}_{index}", "") for name in ("quote", "start_ms", "end_ms")
        )
        if not quote and not start and not end:
            continue
        if not quote or text.count(quote) != 1:
            raise CaseConflict("operational_transcript_quote_ambiguous")
        offset = text.index(quote)
        result.append(
            {
                "char_start": offset,
                "char_end": offset + len(quote),
                "start_ms": integer(request, f"start_ms_{index}"),
                "end_ms": integer(request, f"end_ms_{index}"),
            }
        )
    return result


@csrf_protect
def login(request):
    refused = boundary(request, ("GET", "HEAD", "POST"))
    if refused is not None:
        return refused
    try:
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if request.method == "POST":
            form(request, {"credential"})
            authority, authority_epoch = policy()
            actor = identity.authenticate(directory, request.POST.get("credential"))
            before = identity.epoch(directory)
            response = access.set_cookie(request, HttpResponse(status=303), directory, actor)
            current = policy()
            if (
                current[0] is not authority
                or current[1] != authority_epoch
                or identity.epoch(directory) != before
            ):
                raise CaseConflict("operational_login_changed")
            identity.configured(directory)
            response["Location"] = BASE
        else:
            response = render(request, "operational_workspace/login.html", {})
    except CaseConflict:
        return denied(403)
    return private(response, head=request.method == "HEAD")


@csrf_protect
def logout(request):
    refused = boundary(request, ("POST",))
    if refused is not None:
        return refused
    try:
        form(request, set())
    except CaseConflict:
        return denied(400)
    response = HttpResponse(status=303)
    response.delete_cookie(access.COOKIE, path=BASE, samesite="Strict")
    response["Location"] = BASE + "login/"
    return private(response)


@csrf_protect
def workspace(request):
    refused = boundary(request, ("GET", "HEAD", "POST"))
    if refused is not None:
        return refused
    try:
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        actor, deadline = access.current(request, directory)
        provider = identity.RequestDirectory(directory, actor)
        common = dict(
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
            session_deadline=deadline,
        )
        action = request.POST.get("action") if request.method == "POST" else "queue"
        if action == "queue":
            form(request, {"action", "filter"})
            with services.queue_projection(
                selected_filter=request.POST.get("filter", "all"), **common
            ) as result:
                response = render(request, "operational_workspace/queue.html", {"queue": result})
        elif action == "detail":
            form(request, {"action", "case_ref", "section"})
            with services.detail_projection(
                case_ref=request.POST.get("case_ref"), section=request.POST.get("section"), **common
            ) as result:
                response = render(request, "operational_workspace/detail.html", {"detail": result})
        elif action in {
            "coordination",
            "coordination_set",
            "coordination_clear",
            "coordination_priority",
        }:
            response = coordination_views.dispatch(request, action, common)
        elif action == "notes":
            form(request, {"action", "case_ref"})
            with notes.projection(case_ref=request.POST.get("case_ref"), **common) as result:
                response = render(request, "operational_workspace/notes.html", {"notes": result})
        elif action == "publication_manager":
            form(request, {"action", "case_ref"})
            with publication_manager.projection(
                case_ref=request.POST.get("case_ref"), **common
            ) as result:
                response = render(
                    request, "operational_workspace/publication.html", {"publication": result}
                )
        elif action == "publication_decide":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "edition_id",
                    "content_sha256",
                    "decision",
                    "confirmed",
                    "sequence",
                    "revision",
                    "evidence_version",
                },
            )
            with publication_manager.decide(
                case_ref=request.POST.get("case_ref"),
                edition_id=request.POST.get("edition_id"),
                content_sha256=request.POST.get("content_sha256"),
                action=request.POST.get("decision"),
                confirmed=request.POST.get("confirmed") == "yes",
                expected_actions=integer(request, "sequence"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/publication.html", {"publication": result}
                )
        elif action == "transcript_editor":
            form(request, {"action", "case_ref"})
            with transcripts.projection(case_ref=request.POST.get("case_ref"), **common) as result:
                response = render(
                    request, "operational_workspace/transcripts.html", {"editor": result}
                )
        elif action == "transcript_save":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "part_id",
                    "part_sha256",
                    "text",
                    "change_kind",
                    "note",
                    "version",
                    "command_id",
                    "revision",
                    "evidence_version",
                    *(
                        f"{name}_{index}"
                        for index in range(6)
                        for name in ("quote", "start_ms", "end_ms")
                    ),
                },
            )
            with transcripts.save(
                case_ref=request.POST.get("case_ref"),
                part_id=request.POST.get("part_id"),
                part_sha256=request.POST.get("part_sha256"),
                text=request.POST.get("text"),
                segments=transcript_segments(request),
                change_kind=request.POST.get("change_kind"),
                note=request.POST.get("note"),
                expected_version=integer(request, "version"),
                command_id=request.POST.get("command_id"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/transcripts.html", {"editor": result}
                )
        elif action == "transcript_decide":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "transcript_id",
                    "transcript_digest",
                    "decision",
                    "note",
                    "confirmed",
                    "sequence",
                    "command_id",
                    "revision",
                    "evidence_version",
                },
            )
            with transcripts.decide(
                case_ref=request.POST.get("case_ref"),
                transcript_id=request.POST.get("transcript_id"),
                transcript_digest=request.POST.get("transcript_digest"),
                action=request.POST.get("decision"),
                note=request.POST.get("note"),
                confirmed=request.POST.get("confirmed") == "yes",
                expected_actions=integer(request, "sequence"),
                command_id=request.POST.get("command_id"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/transcripts.html", {"editor": result}
                )
        elif action == "transcript_audio":
            form(request, {"action", "case_ref", "part_id", "part_sha256"})
            with transcripts.audio_projection(
                case_ref=request.POST.get("case_ref"),
                part_id=request.POST.get("part_id"),
                part_sha256=request.POST.get("part_sha256"),
                **common,
            ) as result:
                response = HttpResponse(result["raw"], content_type=result["media_type"])
                response["Content-Disposition"] = f'inline; filename="{result["filename"]}"'
                response["Content-Length"] = str(len(result["raw"]))
        elif action == "lesson_links":
            form(request, {"action", "case_ref"})
            with lesson_links.projection(case_ref=request.POST.get("case_ref"), **common) as result:
                response = render(
                    request, "operational_workspace/lesson_links.html", {"lessons": result}
                )
        elif action == "lesson_link_propose":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "lesson_version_id",
                    "lesson_sha256",
                    "reason",
                    "command_id",
                    "revision",
                    "evidence_version",
                    "target_revision",
                    "target_evidence_version",
                    "start_ms",
                    "end_ms",
                },
            )
            with lesson_links.propose(
                case_ref=request.POST.get("case_ref"),
                lesson_version_id=request.POST.get("lesson_version_id"),
                lesson_sha256=request.POST.get("lesson_sha256"),
                reason=request.POST.get("reason"),
                command_id=request.POST.get("command_id"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                expected_target_revision=integer(request, "target_revision"),
                expected_target_evidence_version=integer(request, "target_evidence_version"),
                start_ms=optional_integer(request, "start_ms"),
                end_ms=optional_integer(request, "end_ms"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/lesson_links.html", {"lessons": result}
                )
        elif action == "lesson_link_decide":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "link_id",
                    "link_sha256",
                    "decision",
                    "note",
                    "confirmed",
                    "command_id",
                    "sequence",
                    "revision",
                    "evidence_version",
                    "target_revision",
                    "target_evidence_version",
                },
            )
            with lesson_links.decide(
                case_ref=request.POST.get("case_ref"),
                link_id=request.POST.get("link_id"),
                link_sha256=request.POST.get("link_sha256"),
                action=request.POST.get("decision"),
                note=request.POST.get("note"),
                confirmed=request.POST.get("confirmed") == "yes",
                command_id=request.POST.get("command_id"),
                expected_sequence=integer(request, "sequence"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                expected_target_revision=integer(request, "target_revision"),
                expected_target_evidence_version=integer(request, "target_evidence_version"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/lesson_links.html", {"lessons": result}
                )
        elif action == "metadata_editor":
            form(request, {"action", "case_ref"})
            with metadata.projection(case_ref=request.POST.get("case_ref"), **common) as result:
                response = render(
                    request, "operational_workspace/metadata.html", {"metadata": result}
                )
        elif action in {"metadata_tags", "metadata_types"}:
            field = "tags" if action == "metadata_tags" else "question_types"
            form(
                request,
                {
                    "action",
                    "case_ref",
                    field,
                    "command_id",
                    "metadata_version",
                    "revision",
                    "evidence_version",
                },
                multiple=("question_types",),
            )
            values = (
                request.POST.get("tags", "").splitlines()
                if field == "tags"
                else request.POST.getlist("question_types")
            )
            with metadata.update(
                case_ref=request.POST.get("case_ref"),
                field=field,
                values=values,
                command_id=request.POST.get("command_id"),
                expected_metadata_version=integer(request, "metadata_version"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/metadata.html", {"metadata": result}
                )
        elif action == "metadata_classify":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "version_id",
                    "version_digest",
                    "primary",
                    "additional",
                    "reason",
                    "confirmed",
                    "command_id",
                    "classification_version",
                    "revision",
                    "evidence_version",
                },
                multiple=("additional",),
            )
            with metadata.bind_classification(
                case_ref=request.POST.get("case_ref"),
                version_id=request.POST.get("version_id"),
                version_digest=request.POST.get("version_digest"),
                primary=request.POST.get("primary"),
                additional=request.POST.getlist("additional"),
                reason=request.POST.get("reason"),
                confirmed=request.POST.get("confirmed") == "yes",
                command_id=request.POST.get("command_id"),
                expected_classification_version=integer(request, "classification_version"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                **common,
            ) as result:
                response = render(
                    request, "operational_workspace/metadata.html", {"metadata": result}
                )
        elif action == "add_note":
            form(
                request,
                {
                    "action",
                    "case_ref",
                    "note",
                    "command_id",
                    "metadata_version",
                    "revision",
                    "evidence_version",
                },
            )
            with notes.append(
                case_ref=request.POST.get("case_ref"),
                note=request.POST.get("note"),
                command_id=request.POST.get("command_id"),
                expected_metadata_version=integer(request, "metadata_version"),
                expected_revision=integer(request, "revision"),
                expected_evidence_version=integer(request, "evidence_version"),
                **common,
            ) as result:
                response = render(request, "operational_workspace/notes.html", {"notes": result})
        else:
            raise CaseConflict("operational_action_unavailable")
    except CaseConflict:
        return denied()
    except (DatabaseError, SyntheticWriteDenied, MaintenanceUnavailable):
        return denied(503)
    return private(response, head=request.method == "HEAD")
