"""Dispatch to existing authenticated views; the panel cookie grants no authority."""

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.case_delivery_desk.views import desk as delivery_desk
from apps.casework_web.access import current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.mufti_review.identity import IdentityUnavailable
from apps.requester_access_review.views import staff as access_review
from apps.team_updates.views import inbox as updates_inbox
from apps.team_workspace.views import workspace as team_workspace
from apps.transcript_case_links.views import ACTIONS as TRANSCRIPT_ACTIONS
from apps.transcript_case_links.views import staff as transcript_desk

PANEL_COOKIE = "fatwa_team_panel"
STAFF = "/casework/staff/"
ACCESS_ACTIONS = frozenset({"access_queue", "access_acknowledge", "access_close"})
UPDATE_ACTIONS = frozenset({"updates_filter", "updates_seen"})
DELIVERY_ACTIONS = frozenset({"prepare", "export", "stage", "quarantine"})
PANELS = {
    "access": access_review,
    "updates": updates_inbox,
    "cases": team_workspace,
    "delivery": delivery_desk,
}


def _panel(response, panel):
    # This is a UI preference only. Never store case IDs, tokens, roles or identity.
    # The selected handler must authenticate again on every request.
    response.set_cookie(
        PANEL_COOKIE, panel, max_age=900, httponly=True, samesite="Strict", path=STAFF, secure=False
    )
    return response


@sensitive_post_parameters("text", "note", "token")
@csrf_protect
def staff(request):
    try:
        if request.method in ("GET", "HEAD"):
            handler = PANELS.get(request.COOKIES.get(PANEL_COOKIE), team_workspace)
            return handler(request)
        action = request.POST.get("action", "")
        if django_apps.is_installed("apps.research_workspace"):
            from apps.research_workspace.views import ACTIONS as RESEARCH_ACTIONS
            from apps.research_workspace.views import workspace as research_workspace

            if action in RESEARCH_ACTIONS:
                return _panel(research_workspace(request), "cases")
        if django_apps.is_installed("apps.pilot_workbench"):
            from apps.pilot_workbench.views import ACTIONS as PILOT_ACTIONS
            from apps.pilot_workbench.views import desk as pilot_desk

            if action in PILOT_ACTIONS:
                return _panel(pilot_desk(request), "cases")
        if django_apps.is_installed("apps.source_rights"):
            from apps.source_rights.views import ACTIONS as RIGHTS_ACTIONS
            from apps.source_rights.views import workspace as rights_workspace

            if action in RIGHTS_ACTIONS:
                return _panel(rights_workspace(request), "cases")
        if django_apps.is_installed("apps.source_case_intake"):
            from apps.source_case_intake.views import ACTIONS as SOURCE_ACTIONS
            from apps.source_case_intake.views import desk as source_desk

            if action in SOURCE_ACTIONS:
                return _panel(source_desk(request), "cases")
        if django_apps.is_installed("apps.knowledge_links"):
            from apps.knowledge_links.views import ACTIONS as KNOWLEDGE_ACTIONS
            from apps.knowledge_links.views import workspace as knowledge

            if action in KNOWLEDGE_ACTIONS:
                return _panel(knowledge(request), "cases")
        if django_apps.is_installed("apps.composite_delivery"):
            from apps.composite_delivery.views import ACTIONS as COMPOSITE_ACTIONS
            from apps.composite_delivery.views import desk as composite

            if action in COMPOSITE_ACTIONS:
                return _panel(composite(request), "cases")
        if action in {"answer_media", "answer_media_save", "answer_media_release", "answer_media_reorder"}:
            from apps.answer_media.views import staff as answer_media

            return _panel(answer_media(request), "cases")
        if action in {"attachment_list", "attachment_preview", "attachment_download"}:
            from apps.case_attachments.views import staff as attachments

            return _panel(attachments(request), "cases")
        if action in {"citations", "citation_search", "citation_select", "citation_save", "citation_source", "citation_compose"}:
            from apps.case_citations.views import desk as citations

            return _panel(citations(request), "cases")
        if action in {"pub_open", "pub_correct", "pub_create", "pub_review", "pub_approve", "pub_withdraw", "pub_library", "pub_read"}:
            from apps.experimental_publication.views import workspace as publication

            return _panel(publication(request), "cases")
        if action in TRANSCRIPT_ACTIONS:
            response = transcript_desk(request)
            if response.status_code == 200:
                _panel(response, "cases")
            return response
        if action in {"journey_cases", "journey_delivery"}:
            _form(request, {"action"})
            current_staff(request, _provider())
            panel = "delivery" if action == "journey_delivery" else "cases"
            return private(_panel(HttpResponse(status=303, headers={"Location": STAFF}), panel))
        if action in DELIVERY_ACTIONS or (
            action == "open" and request.COOKIES.get(PANEL_COOKIE) == "delivery"
        ):
            response = delivery_desk(request)
            if response.status_code in (200, 303):
                _panel(response, "delivery")
            return response
        panel = (
            "access"
            if action in ACCESS_ACTIONS
            else "updates"
            if action in UPDATE_ACTIONS
            else "cases"
        )
        handler = PANELS[panel]
        response = handler(request)
        if response.status_code in (200, 303):
            _panel(response, panel)
        return response
    except (InvalidForm, SuspiciousOperation):
        return denied("staff_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)


def requester(request):
    """Explicit V10 opt-in; preserve the independently guarded V9 composition."""
    if getattr(settings, "FATWA_REQUESTER_PORTAL_ENABLED", False) is True:
        from apps.requester_portal.views import portal

        return portal(request)
    from apps.requester_access_review.views import requester as existing_requester

    return existing_requester(request)
