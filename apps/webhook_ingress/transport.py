"""Fail-closed, account-scoped Meta/Telegram webhook admission.

The outer casework guard calls this BEFORE its budget and before view dispatch.
A profile is *synthetic only*, bound to one UUID route and one external account.
Neither HMAC authenticity nor a provider sender ID is a Mufti approval.
"""

import hashlib
import hmac
import re
from uuid import UUID

from django.conf import settings

from apps.source_case_intake.adapters import IntakeError, SourceContext

ROUTE = re.compile(r"^/casework/webhooks/([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})/$")
SHA256 = re.compile(r"^sha256=([a-fA-F0-9]{64})$")
CHALLENGE = re.compile(r"^[0-9]{1,32}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
SOURCES = frozenset({"telegram", "facebook", "messenger", "instagram", "whatsapp"})


def _configured(request):
    if (
        getattr(settings, "FATWA_WEBHOOK_INGRESS_ENABLED", False) is not True
        or getattr(settings, "FATWA_SOURCE_CASE_INTAKE_ENABLED", False) is not True
    ):
        return None
    match = ROUTE.fullmatch(request.path)
    if not match:
        return None
    profiles = getattr(settings, "FATWA_WEBHOOK_INGRESS_PROFILES", None)
    if type(profiles) is not dict:
        return None
    key = str(UUID(match[1]))
    profile = profiles.get(key)
    if type(profile) is not dict or set(profile) != {
        "source", "account", "conversation", "secret", "verify_token"
    }:
        return None
    source = profile["source"]
    secret = profile["secret"]
    verify = profile["verify_token"]
    if (
        type(source) is not str
        or source not in SOURCES
        or type(secret) is not str
        or not TOKEN.fullmatch(secret)
        or type(verify) is not str
        or not TOKEN.fullmatch(verify)
    ):
        return None
    try:
        context = SourceContext(source, profile["account"], profile["conversation"])
        context.validate()
    except (TypeError, IntakeError):
        return None
    return context, secret, verify


def _verification(request, verify):
    if request.method != "GET" or "telegram" == request._fatwa_webhook_context.source:
        return ("webhook_method_unavailable", 405)
    # GET/POST may never share cookies/CSRF state or route to a public reader.
    if set(request.GET) != {"hub.mode", "hub.challenge", "hub.verify_token"}:
        return ("webhook_verification_invalid", 403)
    if any(len(values) != 1 for _, values in request.GET.lists()):
        return ("webhook_verification_invalid", 403)
    if request.GET["hub.mode"] != "subscribe" or not CHALLENGE.fullmatch(
        request.GET["hub.challenge"]
    ):
        return ("webhook_verification_invalid", 403)
    supplied = request.GET["hub.verify_token"]
    if not hmac.compare_digest(supplied.encode("utf-8"), verify.encode("ascii")):
        return ("webhook_verification_invalid", 403)
    request._fatwa_webhook_challenge = request.GET["hub.challenge"]
    return None


def _notification(request, secret):
    if request.META.get("QUERY_STRING"):
        return ("webhook_query_not_supported", 400)
    if request.content_type != "application/json":
        return ("webhook_content_type_invalid", 415)
    # Request body is read before any JSON decoding, normalization or logging.
    try:
        raw = request.body
    except (ValueError, OverflowError, OSError):
        return ("webhook_body_unavailable", 413)
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 262144:
        return ("webhook_body_bound", 413)
    source = request._fatwa_webhook_context.source
    if source == "telegram":
        supplied = request.META.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
        good = type(supplied) is str and hmac.compare_digest(
            supplied.encode("utf-8"), secret.encode("ascii")
        )
    else:
        header = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
        matched = SHA256.fullmatch(header) if type(header) is str else None
        good = matched is not None and hmac.compare_digest(
            matched[1].lower(),
            hmac.new(secret.encode("ascii"), raw, hashlib.sha256).hexdigest()
        )
    if not good:
        return ("webhook_signature_invalid", 403)
    request._fatwa_webhook_raw = raw
    return None


def admit_request(request):
    """Return a (safe_code, HTTP_status) on denial, else bind verified inputs.

    Unknown/unconfigured profiles stay closed. No raw input or secret is logged;
    URLs, query tokens and HTTP payload fields cannot choose the account scope.
    """
    configured = _configured(request)
    if configured is None:
        return ("webhook_profile_unavailable", 404)
    context, secret, verify = configured
    request._fatwa_webhook_context = context
    if request.method == "GET":
        return _verification(request, verify)
    if request.method == "POST":
        return _notification(request, secret)
    return ("webhook_method_unavailable", 405)
