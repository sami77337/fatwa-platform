"""Native pre-authentication forms; no staff cookie before independent factors."""

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework.services import CaseConflict
from apps.casework_web import access
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form
from apps.mufti_review.identity import IdentityUnavailable

from . import integration, services

PENDING_SALT = "fatwa.staff-mfa.pending.v1"
PATHS = {"CASEWORK": "/casework/staff/mfa/", "OPERATIONS": "/casework/operations/mfa/"}
HOMES = {"CASEWORK": "/casework/staff/", "OPERATIONS": "/casework/operations/"}


def cookie(surface):
    return "fatwa_mfa_" + surface.lower()


def cookie_path(surface):
    return "/casework/" if surface == "CASEWORK" else "/casework/operations/"


def _common(request, provider, surface):
    return dict(
        provider=provider, surface=surface, browser_binding=integration.binding(request, surface)
    )


def _page(request, challenge, *, surface, provider, manual_key="", setup=None):
    get_token(request)
    state = services.describe(challenge, **_common(request, provider, surface))
    return private(
        render(
            request,
            "staff_mfa/page.html",
            {
                "pending": state,
                "surface": surface,
                "path": PATHS[surface],
                "home": HOMES[surface],
                "manual_key": manual_key,
                "setup": setup,
            },
        )
    )


def _clear_staff(response, surface):
    if surface == "CASEWORK":
        response.delete_cookie(access.COOKIE, path="/casework/", samesite="Strict")
    else:
        from apps.operational_workspace.access import COOKIE

        response.delete_cookie(COOKIE, path="/casework/operations/", samesite="Strict")


@sensitive_post_parameters("credential", "code", "recovery_code")
@integration.native
def begin(request, *, provider, surface, credential, purpose="LOGIN", expected_actor=None):
    try:
        if request.method != "POST":
            return denied("staff_mfa_method_not_allowed", 405)
        rotate_token(request)
        row = services.start(
            credential=credential,
            purpose=purpose,
            expected_actor=expected_actor,
            **_common(request, provider, surface),
        )
        response = _page(request, str(row.id), surface=surface, provider=provider)
        response.set_signed_cookie(
            cookie(surface),
            str(row.id),
            salt=PENDING_SALT,
            max_age=300,
            httponly=True,
            samesite="Strict",
            secure=False,
            path=cookie_path(surface),
        )
        _clear_staff(response, surface)
        return private(response)
    except IdentityUnavailable:
        return denied("staff_mfa_not_authorized", 403)
    except DatabaseError:
        return denied("staff_mfa_store_unavailable", 503)


def _actor(request, provider, surface):
    if surface == "CASEWORK":
        return access.current_staff(request, provider)
    from apps.operational_workspace.access import current

    return current(request, provider)[0]


@sensitive_post_parameters("credential", "code", "recovery_code")
@csrf_protect
@integration.native
def page(request, *, surface):
    if not integration.enabled() or request.path != PATHS.get(surface):
        return denied("staff_mfa_unavailable", 404)
    if request.method not in {"GET", "HEAD", "POST"}:
        return denied("staff_mfa_method_not_allowed", 405)
    if request.META.get("QUERY_STRING"):
        return denied("staff_mfa_form_invalid", 400)
    try:
        provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        identifier = request.get_signed_cookie(
            cookie(surface), default="", salt=PENDING_SALT, max_age=300
        )
        if request.method in {"GET", "HEAD"}:
            if identifier:
                response = _page(request, identifier, surface=surface, provider=provider)
            else:
                actor = _actor(request, provider, surface)
                managed = services.manage(provider=provider, actor=actor)
                response = private(
                    render(
                        request,
                        "staff_mfa/page.html",
                        {
                            "managed": managed,
                            "path": PATHS[surface],
                            "home": HOMES[surface],
                        },
                    )
                )
            if request.method == "HEAD":
                response.content = b""
            return response
        action = request.POST.get("action")
        schemas = {
            "enroll": {"action"},
            "verify": {"action", "code"},
            "recover": {"action", "recovery_code"},
            "revoke_start": {"action", "credential"},
        }
        if action not in schemas:
            raise InvalidForm("unsupported_action")
        form = _form(request, schemas[action])
        if action == "revoke_start":
            actor = _actor(request, provider, surface)
            services.manage(provider=provider, actor=actor)
            return begin(
                request,
                provider=provider,
                surface=surface,
                credential=form["credential"],
                purpose="REVOKE",
                expected_actor=actor,
            )
        if not identifier:
            services.reject()
        common = _common(request, provider, surface)
        if action == "enroll":
            factor, manual = services.enroll(identifier, **common)
            return _page(
                request,
                identifier,
                surface=surface,
                provider=provider,
                manual_key=manual,
                setup={
                    "algorithm": factor.algorithm,
                    "digits": factor.digits,
                    "period": factor.period,
                },
            )
        if action == "recover":
            services.recover(identifier, recovery_code=form["recovery_code"], **common)
            return _page(request, identifier, surface=surface, provider=provider)
        with services.complete(identifier, code=form["code"], **common) as (grant, codes):
            if grant.proof.purpose == "REVOKE":
                services.revoke(grant)
                response = HttpResponse(status=303, headers={"Location": HOMES[surface] + "login/"})
                _clear_staff(response, surface)
            else:
                response = (
                    render(
                        request,
                        "staff_mfa/page.html",
                        {
                            "completed": True,
                            "codes": codes,
                            "home": HOMES[surface],
                            "path": PATHS[surface],
                        },
                    )
                    if codes
                    else HttpResponse(status=303, headers={"Location": HOMES[surface]})
                )
                if surface == "CASEWORK":
                    access.set_staff_cookie(
                        request, response, provider, grant.guard.actor, mfa_grant=grant
                    )
                else:
                    from apps.operational_workspace.access import set_cookie

                    set_cookie(request, response, provider, grant.guard.actor, mfa_grant=grant)
            response.delete_cookie(cookie(surface), path=cookie_path(surface), samesite="Strict")
            return private(response)
    except (IdentityUnavailable, CaseConflict):
        return denied("staff_mfa_not_authorized", 403)
    except (InvalidForm, ValueError, TypeError):
        return denied("staff_mfa_form_invalid", 400)
    except DatabaseError:
        return denied("staff_mfa_store_unavailable", 503)
