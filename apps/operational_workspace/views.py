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

from . import access, identity, services
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


def form(request, fields):
    if (
        request.FILES
        or set(request.POST) - fields - {"csrfmiddlewaretoken"}
        or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
    ):
        raise CaseConflict("operational_form_invalid")


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
        else:
            raise CaseConflict("operational_action_unavailable")
    except CaseConflict:
        return denied()
    except (DatabaseError, SyntheticWriteDenied, MaintenanceUnavailable):
        return denied(503)
    return private(response, head=request.method == "HEAD")
