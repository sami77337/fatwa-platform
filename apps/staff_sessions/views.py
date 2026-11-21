"""Native explicit selection, credential verification and separate confirmation."""

from datetime import timedelta
from hmac import compare_digest

from django.conf import settings
from django.core import signing
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework.services import CaseConflict
from apps.casework_web import access
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.mufti_review.identity import IdentityUnavailable

from . import integration, services

SALT = "fatwa.staff-session-confirmation.v1"


def principal(request):
    provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if request.path == "/casework/operations/sessions/":
        from apps.operational_workspace.access import current

        actor, _ = current(request, provider)
        surface = "OPERATIONS"
    else:
        actor = access.current_staff(request, provider)
        surface = "CASEWORK"
    return integration.capture(provider, actor, surface=surface)


def _ticket(request, binding, row):
    value = {
        "session": binding.id,
        "target": str(row.id),
        "digest": row.digest,
        "operation": services.OPERATION,
        "until": min(binding.deadline, timezone.now() + timedelta(minutes=5)).isoformat(),
    }
    value["browser"] = browser_proof(request, SALT, services.encode(value))
    return signing.dumps(value, salt=SALT, compress=False)


def _verify_ticket(request, binding, row, token):
    if type(token) is not str or len(token) > 2048:
        services.reject()
    try:
        value = signing.loads(token, salt=SALT, max_age=300)
        from datetime import datetime

        if (
            type(value) is not dict
            or set(value) != {"session", "target", "digest", "operation", "until", "browser"}
            or any(type(v) is not str for v in value.values())
        ):
            services.reject()
        signature = value.pop("browser")
        until = datetime.fromisoformat(value["until"])
        if (
            not timezone.is_aware(until)
            or not timezone.now() < until <= binding.deadline
            or value["session"] != binding.id
            or value["target"] != str(row.id)
            or value["digest"] != row.digest
            or value["operation"] != services.OPERATION
            or not compare_digest(signature, browser_proof(request, SALT, services.encode(value)))
        ):
            services.reject()
    except (signing.BadSignature, ValueError, TypeError, KeyError) as exc:
        raise IdentityUnavailable("staff_session_confirmation_required") from exc


def _page(request, binding, *, target=None, proof=None, required=None):
    get_token(request)
    with services.listing(binding) as rows:
        return private(
            render(
                request,
                "staff_sessions/page.html",
                {
                    "rows": rows,
                    "target": target,
                    "proof": proof,
                    "required": required,
                    "ticket": _ticket(request, binding, target) if target else "",
                    "surface": binding.surface,
                },
            )
        )


@sensitive_post_parameters("credential", "ticket", "proof_id")
@csrf_protect
def page(request):
    if request.method not in {"GET", "HEAD", "POST"}:
        return denied("staff_session_method_not_allowed", 405)
    if request.META.get("QUERY_STRING"):
        return denied("staff_session_form_invalid", 400)
    try:
        binding = principal(request)
        if binding is None:
            services.reject()
        if request.method in {"GET", "HEAD"}:
            return _page(request, binding)
        action = request.POST.get("action")
        schemas = {
            "select": {"action", "target_id"},
            "reauthenticate": {"action", "target_id", "ticket", "credential"},
            "revoke": {"action", "target_id", "ticket", "proof_id"},
        }
        if action not in schemas:
            raise InvalidForm("unsupported_action")
        fields = _form(request, schemas[action])
        row, rule = services.inspect(binding, fields["target_id"])
        if action == "select":
            return _page(request, binding, target=row, required=rule.required)
        _verify_ticket(request, binding, row, fields["ticket"])
        if action == "reauthenticate":
            proof = services.authenticate_fresh(
                binding, target_id=row.id, credential=fields["credential"]
            )
            return _page(request, binding, target=row, proof=proof, required=rule.required)
        services.revoke(binding, target_id=row.id, proof_id=fields["proof_id"])
        if str(row.id) == binding.id:
            rotate_token(request)
            if binding.surface == "CASEWORK":
                cookie, path, login = access.COOKIE, "/casework/", "/casework/staff/login/"
            else:
                from apps.operational_workspace import access as operations

                cookie, path, login = operations.COOKIE, operations.BASE, operations.BASE + "login/"
            response = HttpResponse(status=303, headers={"Location": login})
            response.delete_cookie(cookie, path=path, samesite="Strict")
        else:
            response = HttpResponse(status=303, headers={"Location": request.path})
        return private(response)
    except (InvalidForm, ValueError, TypeError) as exc:
        if isinstance(exc, IdentityUnavailable):
            return denied("staff_session_not_authorized", 403)
        return denied("staff_session_form_invalid", 400)
    except CaseConflict:
        return denied("staff_session_not_authorized", 403)
    except DatabaseError:
        return denied("staff_session_store_unavailable", 503)
