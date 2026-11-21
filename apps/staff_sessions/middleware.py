"""Bound request lifetime and response rechecks, including streamed private readers."""

from django.conf import settings
from django.db import DatabaseError

from apps.casework.services import CaseConflict
from apps.casework_web.guard import denied
from apps.mufti_review.identity import IdentityUnavailable

from . import integration

LOGOUTS = {"/casework/staff/logout/": "CASEWORK", "/casework/operations/logout/": "OPERATIONS"}


def _logout_binding(request):
    if request.method != "POST" or request.path not in LOGOUTS:
        return None
    provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if LOGOUTS[request.path] == "CASEWORK":
        from apps.casework_web.access import COOKIE, current_staff

        if not request.COOKIES.get(COOKIE):
            return None
        actor = current_staff(request, provider)
    else:
        from apps.operational_workspace.access import COOKIE, current

        if not request.COOKIES.get(COOKIE):
            return None
        actor, _ = current(request, provider)
    return integration.capture(provider, actor, surface=LOGOUTS[request.path])


def _check(lease, response):
    from . import services

    for binding in lease.bindings.values():
        if binding.id in lease.closed_by_request:
            if (
                response.status_code != 303
                or response.streaming
                or response.content
                or response.get("Location")
                not in {"/casework/staff/login/", "/casework/operations/login/"}
            ):
                services.reject()
        else:
            services.recheck(binding)
    # A later binding's callback can revoke a previously checked session or
    # source. Finish every callback first, then perform only retained pure pins.
    for binding in lease.bindings.values():
        if binding.id not in lease.closed_by_request:
            services.check(binding, authorize=False)
    integration.check_final_guards(lease)


def _stream(iterator, lease, response):
    try:
        with integration.request_context(lease, close=False):
            for part in iterator:
                _check(lease, response)
                yield part
    finally:
        lease.active = False
        close = getattr(iterator, "close", None)
        if callable(close):
            close()


class SessionContext:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view, args, kwargs):
        if integration.enabled():
            try:
                request._staff_session_logout_binding = _logout_binding(request)
            except (IdentityUnavailable, CaseConflict):
                # Do not report successful server logout after a temporary USE
                # denial if the copied cookie could become valid again later.
                return denied("staff_session_not_authorized", 403)
            except DatabaseError:
                return denied("staff_session_store_unavailable", 503)
        return None

    def __call__(self, request):
        if not integration.enabled():
            return self.get_response(request)
        with integration.request_context(close=False) as lease:
            try:
                response = self.get_response(request)
                logout_binding = getattr(request, "_staff_session_logout_binding", None)
                if logout_binding is not None and response.status_code == 303:
                    from . import services

                    services.revoke(logout_binding, target_id=logout_binding.id, logout=True)
                _check(lease, response)
                if response.streaming:
                    iterator = iter(response.streaming_content)
                    response.streaming_content = _stream(iterator, lease, response)
                    response._resource_closers.append(lambda: setattr(lease, "active", False))
                else:
                    lease.active = False
                return response
            except integration.ResponseProjectionDenied as exc:
                lease.active = False
                response = denied(str(exc), 404)
                response["Referrer-Policy"] = "no-referrer"
                return response
            except (IdentityUnavailable, CaseConflict):
                lease.active = False
                return denied("staff_session_not_authorized", 403)
            except DatabaseError:
                lease.active = False
                return denied("staff_session_store_unavailable", 503)
            except BaseException:
                lease.active = False
                raise
