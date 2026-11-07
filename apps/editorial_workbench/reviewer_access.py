"""Short-lived reviewer access for the separate loopback training desk."""

import os
from hmac import compare_digest

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .source_review_identity import authenticate_fixture_reviewer

_COOKIE = "fatwa_training_reviewer"
_TTL = 30 * 60


def browser_proof(request, purpose, value):
    # Django retains a stable, per-browser secret behind the form's freshly masked CSRF token.
    get_token(request)
    return salted_hmac(
        purpose, request.META["CSRF_COOKIE"] + "|" + value, algorithm="sha256"
    ).hexdigest()


def _cookie_salt():
    return "training.desk.login." + os.environ.get("FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256", "")


def signed_in(request):
    saved = request.get_signed_cookie(_COOKIE, default="", salt=_cookie_salt(), max_age=_TTL)
    return bool(saved) and compare_digest(
        saved, browser_proof(request, "training.staff", "reviewer")
    )


@sensitive_post_parameters("token")
@require_http_methods(["GET", "HEAD", "POST"])
def reviewer_login(request):
    def page(message="", status=200):
        return render(
            request, "editorial_workbench/reviewer_login.html", {"message": message}, status=status
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
        authenticate_fixture_reviewer(fields["token"])
    except SuspiciousOperation:
        return page("تعذّرت قراءة نموذج الدخول.", 400)
    except ValueError:
        return page("تعذّر التحقق من رمز المراجع.", 403)
    rotate_token(request)
    response = HttpResponse(status=303, headers={"Location": reverse("reviewer_desk")})
    response.set_signed_cookie(
        _COOKIE,
        browser_proof(request, "training.staff", "reviewer"),
        salt=_cookie_salt(),
        max_age=_TTL,
        httponly=True,
        samesite="Strict",
        path="/review/",
    )
    return response


@require_POST
def reviewer_logout(request):
    rotate_token(request)
    response = HttpResponse(status=303, headers={"Location": reverse("reviewer_login")})
    response.delete_cookie(_COOKIE, path="/review/", samesite="Strict")
    return response
