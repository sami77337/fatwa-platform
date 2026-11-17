"""Opt-in inbox at the existing guarded staff route; case actions stay in their owner."""

from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as casework
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider, staff
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, validate_identity

from .services import KINDS, mark_seen, read_inbox

PAGE_SIZE = 20


def _proof(request, provider_id, subject_id, case_ref, sequence):
    return browser_proof(request, "team.updates.seen.v1",
                         f"{provider_id}|{subject_id}|{case_ref}|{sequence}")


def _page(request, provider, identity, *, state="unread", kind="all", page=1, message=""):
    updates = read_inbox(subject_id=identity.subject_id, provider=provider,
                         synthetic_fixtures_only=True)
    unread = sum(not row["seen"] for row in updates)
    filtered = [row for row in updates if (state == "all" or not row["seen"])
                and (kind == "all" or row["kind"] == kind)]
    pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    visible = filtered[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    get_token(request)
    for row in visible:
        row["proof"] = _proof(request, provider.provider_id, identity.subject_id,
                              row["case_ref"], row["sequence"])
    return private(render(request, "team_updates/inbox.html", {
        "updates": visible, "unread": unread, "total": len(updates), "matches": len(filtered),
        "kinds": KINDS.items(), "state": state, "kind": kind, "message": message,
        "page": page, "pages": pages, "previous": page - 1 if page > 1 else None,
        "next": page + 1 if page < pages else None,
    }))


@csrf_protect
def inbox(request):
    if request.method == "POST" and request.POST.get("action", "") not in {
        "updates_filter", "updates_seen",
    }:
        # Server-configured seam can point to #212's workspace; no copied case workflow.
        case_view = getattr(settings, "FATWA_TEAM_UPDATES_CASE_VIEW", staff)
        return case_view(request)
    try:
        provider = _provider()
        provider_id = provider.provider_id
        identity = current_staff(request, provider)
        provider = RequestDirectory(provider, identity, authenticated_provider_id=provider_id)
        if request.method in ("GET", "HEAD"):
            return _page(request, provider, identity)
        action = request.POST.get("action", "")
        if action == "updates_filter":
            fields = _form(request, {"action", "state", "kind", "page"})
            if fields["state"] not in {"all", "unread"} or fields["kind"] not in {"all", *KINDS}:
                raise InvalidForm("invalid_filter")
            return _page(request, provider, identity, state=fields["state"], kind=fields["kind"],
                         page=_integer(fields["page"]))
        fields = _form(request, {"action", "case_ref", "sequence", "proof"})
        sequence = _integer(fields["sequence"])
        validate_identity(identity, case_key=fields["case_ref"])
        expected = _proof(request, provider.provider_id, identity.subject_id,
                          fields["case_ref"], sequence)
        if not fields["proof"].isascii() or not compare_digest(expected, fields["proof"]):
            return denied("update_confirmation_invalid", 403)
        rows = casework.list_cases(subject_id=identity.subject_id, provider=provider,
                                   synthetic_fixtures_only=True)
        row = next((row for row in rows if row["public_ref"] == fields["case_ref"]), None)
        if row is None:
            return denied("update_unavailable", 404)
        mark_seen(case_id=row["case_id"], sequence=sequence, subject_id=identity.subject_id,
                  provider=provider, synthetic_fixtures_only=True)
        return _page(request, provider, identity,
                     message="عُلّم هذا التنبيه وحده كمقروء. لم تتغير حالة القضية أو اعتمادها.")
    except (InvalidForm, SuspiciousOperation):
        return denied("updates_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except casework.CaseConflict:
        return denied("update_unavailable", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("updates_store_unavailable", 503)
