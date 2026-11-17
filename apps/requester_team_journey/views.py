"""Dispatch to existing authenticated views; the panel cookie grants no authority."""
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework_web.access import current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.mufti_review.identity import IdentityUnavailable
from apps.requester_access_review.views import staff as access_review
from apps.team_workspace.views import workspace as team_workspace

PANEL_COOKIE = "fatwa_team_panel"
STAFF = "/casework/staff/"
ACCESS_ACTIONS = frozenset({"access_queue", "access_acknowledge", "access_close"})


def _panel(response, panel):
    # This is a UI preference only. Never store case IDs, tokens, roles or identity.
    # The selected handler must authenticate again on every request.
    response.set_cookie(PANEL_COOKIE, panel, max_age=900, httponly=True,
                        samesite="Strict", path=STAFF, secure=False)
    return response


@sensitive_post_parameters("text", "note", "token")
@csrf_protect
def staff(request):
    try:
        if request.method in ("GET", "HEAD"):
            handler = access_review if request.COOKIES.get(PANEL_COOKIE) == "access" else team_workspace
            return handler(request)
        action = request.POST.get("action", "")
        if action == "journey_cases":
            _form(request, {"action"})
            current_staff(request, _provider())
            return private(_panel(HttpResponse(status=303, headers={"Location": STAFF}), "cases"))
        panel = "access" if action in ACCESS_ACTIONS else "cases"
        handler = access_review if panel == "access" else team_workspace
        response = handler(request)
        if response.status_code in (200, 303):
            _panel(response, panel)
        return response
    except (InvalidForm, SuspiciousOperation):
        return denied("staff_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
