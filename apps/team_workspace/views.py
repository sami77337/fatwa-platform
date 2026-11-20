"""Native team forms using current MUFTI scope, revision checks and case services."""

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.styles import CSS
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, validate_identity

from .presentation import FILTERS, queue, read_workspace_case

MESSAGES = {
    "draft": "حُفظ إصدار جديد. الإصدارات السابقة باقية في سجل الجواب.",
    "clarify": "سُجل طلب الاستيضاح وأُلغي أي اعتماد سابق. لم يُرسل إلى قناة خارجية.",
    "approve": "اعتمدت هذه النسخة. الاعتماد لا يثبت تسليم الجواب أو قراءته.",
    "return": "أُعيد الجواب للتعديل. احفظ إصدارًا جديدًا قبل إعادة المراجعة.",
}


def stylesheet(request):
    return private(HttpResponse(
        CSS + "\nselect{font:inherit;max-width:100%;width:100%;padding:.55rem;"
        "margin-bottom:.7rem}select:focus,summary:focus{outline:3px solid #9c6800;"
        "outline-offset:3px}summary{cursor:pointer}section{scroll-margin-top:1rem}"
        ".exact{white-space:pre-wrap;overflow-wrap:anywhere}"
        ".mufti-main{max-width:1400px}.mufti-layout{display:grid;"
        "grid-template-columns:minmax(220px,320px) minmax(0,1fr);gap:1rem}"
        ".mufti-context,.mufti-task{min-width:0}.mufti-context details{margin:.8rem 0}"
        ".mufti-context p{overflow-wrap:anywhere}.mufti-case-nav{display:flex;"
        "flex-wrap:wrap;gap:.4rem}.mufti-case-nav form{margin:0;padding:.3rem}"
        ".mufti-case-nav [aria-current=page]{outline:2px solid #12516c}"
        "@media(max-width:850px){.mufti-layout{grid-template-columns:minmax(0,1fr)}}",
        content_type="text/css; charset=utf-8",
    ))


def _page(request, provider, identity, *, common=None, selected_filter="all", query="",
          sort="newest", message="", attempted_text=None, status=200, access=None):
    rows = services.list_cases(
        subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True,
    )
    selected = read_workspace_case(**common) if common else None
    source_origins = None
    if common and getattr(settings, "FATWA_SOURCE_CASE_INTAKE_ENABLED", False) is True:
        from apps.source_case_intake.services import staff_origins

        source_origins = staff_origins(**common)
    get_token(request)
    template = (
        "mufti_workspace/overview.html"
        if selected and getattr(settings, "FATWA_MUFTI_WORKSPACE_ENABLED", False) is True
        else "team_workspace/workspace.html"
    )
    return private(render(request, template, {
        **queue(rows, selected_filter, query, sort=sort), "selected": selected,
        "source_origins": source_origins,
        "composite_delivery_enabled": getattr(settings, "FATWA_COMPOSITE_DELIVERY_ENABLED", False) is True,
        "message": message, "attempted_text": attempted_text, "access": access,
        "attachments_enabled": getattr(settings, "FATWA_CASE_ATTACHMENTS_ENABLED", False) is True,
        "answer_media_enabled": getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", False) is True,
        "citations_enabled": getattr(settings, "FATWA_CASE_CITATIONS_ENABLED", False) is True,
        "publication_enabled": getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is True,
        "recovery_available": callable(getattr(settings, "FATWA_CASEWORK_RECOVERY_RESOLVER", None)),
    }, status=status))


@sensitive_post_parameters("text", "note")
@csrf_protect
def workspace(request):
    try:
        provider = _provider()
        provider_id = provider.provider_id
        identity = current_staff(request, provider)
        provider = RequestDirectory(provider, identity, authenticated_provider_id=provider_id)
        if request.method in ("GET", "HEAD"):
            return _page(request, provider, identity)
        action = request.POST.get("action", "")
        if action == "case_workspace" and getattr(
            settings, "FATWA_MUFTI_WORKSPACE_ENABLED", False
        ) is not True:
            raise InvalidForm("connected_workspace_disabled")
        if action == "filter":
            fields = _form(request, {"action", "state", "query", "sort"})
            from .presentation import SORTS
            if (
                fields["state"] not in FILTERS
                or fields["sort"] not in SORTS
                or len(fields["query"]) > 40
                or "\x00" in fields["query"]
            ):
                raise InvalidForm("invalid_queue_filter")
            return _page(
                request, provider, identity,
                selected_filter=fields["state"], query=fields["query"], sort=fields["sort"],
            )
        required = {"action", "case_ref"}
        if action in {"draft", "clarify"}:
            required |= {"text", "revision", "evidence_version"}
        elif action in {"approve", "return"}:
            required |= {"answer_id", "note", "revision", "evidence_version"}
        elif action not in {"open", "case_workspace", "rotate", "revoke"}:
            raise InvalidForm("unknown_action")
        fields = _form(request, required)
        validate_identity(identity, case_key=fields["case_ref"])
        rows = services.list_cases(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True,
        )
        row = next((row for row in rows if row["public_ref"] == fields["case_ref"]), None)
        if row is None:
            return denied("staff_case_unavailable", 404)
        common = {
            "case_id": row["case_id"], "subject_id": identity.subject_id,
            "provider": provider, "synthetic_fixtures_only": True,
        }
        access = None
        try:
            if action in {"draft", "clarify", "approve", "return"}:
                current = {
                    **common, "expected_revision": _integer(fields["revision"]),
                    "expected_evidence_version": _integer(fields["evidence_version"]),
                }
                if action == "draft":
                    # Keep a draft from implicitly closing a pending clarification.
                    # Check under a case lock, then let the core write recheck these
                    # exact revision pins. Any intervening action increments revision.
                    # The synthetic DB guard deliberately rejects nested transactions.
                    with services._staff_case(
                        common["case_id"], identity.subject_id, provider, True,
                        expected_revision=current["expected_revision"],
                        expected_evidence_version=current["expected_evidence_version"],
                    ) as (case, _identity):
                        if case.stage == "NEEDS_CLARIFICATION":
                            raise services.CaseConflict("clarification_reply_required")
                    services.save_answer(**current, text=fields["text"])
                elif action == "clarify":
                    services.request_clarification(**current, text=fields["text"])
                else:
                    services.record_decision(
                        **current, answer_id=fields["answer_id"], note=fields["note"],
                        action="APPROVE" if action == "approve" else "RETURN_FOR_CHANGES",
                    )
            elif action in {"rotate", "revoke"}:
                resolver = getattr(settings, "FATWA_CASEWORK_RECOVERY_RESOLVER", None)
                if not callable(resolver):
                    return denied("trusted_recovery_unavailable", 503)
                try:
                    requester_id = resolver(identity.subject_id, fields["case_ref"])
                except Exception:
                    return denied("trusted_recovery_unavailable", 503)
                method = services.rotate_access if action == "rotate" else services.revoke_access
                result = method(**common, requester_id=requester_id)
                access = {"token": result.get("token"), "rotated": action == "rotate"}
        except services.CaseConflict:
            # Revalidate identity/scope before showing any refreshed data. A rejected
            # draft is a separate copy buffer, never rebound to fresh revision pins.
            attempted = fields.get("text", fields.get("note", ""))
            if len(attempted) > services.MAX_TEXT or "\x00" in attempted:
                attempted = None
            return _page(
                request, provider, identity, common=common, status=409,
                attempted_text=attempted,
                message="لم يُحفظ الإجراء. راجع الحالة والوقائع الحالية وصحة النص قبل المحاولة مجددًا.",
            )
        return _page(request, provider, identity, common=common,
                     message=MESSAGES.get(action, ""), access=access)
    except (InvalidForm, SuspiciousOperation):
        return denied("staff_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except services.CaseConflict:
        return denied("staff_update_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)
