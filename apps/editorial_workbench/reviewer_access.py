"""Short-lived reviewer access for the separate loopback training desk."""

from hmac import compare_digest

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .source_review_identity import authenticate_fixture_role, credential_digest

_COOKIE_PREFIX = "fatwa_training_"
_TTL = 30 * 60


def browser_proof(request, purpose, value):
    # Django retains a stable, per-browser secret behind the form's freshly masked CSRF token.
    get_token(request)
    return salted_hmac(
        purpose, request.META["CSRF_COOKIE"] + "|" + value, algorithm="sha256"
    ).hexdigest()


def _cookie_salt(role):
    return "training.desk.login." + credential_digest(role)


def signed_in(request, role="reviewer"):
    if not credential_digest(role):
        return False
    saved = request.get_signed_cookie(
        _COOKIE_PREFIX + role, default="", salt=_cookie_salt(role), max_age=_TTL
    )
    return bool(saved) and compare_digest(saved, browser_proof(request, "training.staff", role))


@sensitive_post_parameters("token")
@require_http_methods(["GET", "HEAD", "POST"])
def desk_login(request, role="reviewer"):
    def page(message="", status=200):
        return render(
            request,
            "editorial_workbench/reviewer_login.html",
            {
                "message": message,
                "author_login": role == "author",
                "operator_login": role == "operator",
            },
            status=status,
        )

    if request.META.get("QUERY_STRING"):
        return page("افتح صفحة الدخول دون معاملات إضافية.", 400)
    if request.method != "POST":
        return page()
    if request.content_type != "application/x-www-form-urlencoded":
        return page("استخدم نموذج الدخول المعروض.", 415)
    try:
        fields = request.POST
        if set(fields) - {"csrfmiddlewaretoken"} != {"token"} or any(
            len(fields.getlist(k)) != 1 for k in fields
        ):
            return page("تعذّرت قراءة نموذج الدخول.", 400)
        authenticate_fixture_role(fields["token"], role)
    except SuspiciousOperation:
        return page("تعذّرت قراءة نموذج الدخول.", 400)
    except ValueError:
        return page("تعذّر التحقق من رمز الدخول لهذا المكتب.", 403)
    rotate_token(request)
    response = HttpResponse(
        status=303,
        headers={"Location": reverse({
            "author": "author_queue",
            "operator": "operator_outbox",
            "reviewer": "reviewer_desk",
        }[role])},
    )
    return set_role_cookie(request, response, role)


def set_role_cookie(request, response, role):
    """Attach the role cookie only after authenticating and rotating the CSRF secret."""
    response.set_signed_cookie(
        _COOKIE_PREFIX + role,
        browser_proof(request, "training.staff", role),
        salt=_cookie_salt(role),
        max_age=_TTL,
        httponly=True,
        samesite="Strict",
        path="/review/",
    )
    return response


@require_POST
def desk_logout(request, role="reviewer"):
    rotate_token(request)
    response = HttpResponse(
        status=303,
        headers={"Location": reverse({
            "author": "author_login",
            "operator": "operator_login",
            "reviewer": "reviewer_login",
        }[role])},
    )
    response.delete_cookie(_COOKIE_PREFIX + role, path="/review/", samesite="Strict")
    return response
