"""Short-lived, CSRF-bound staff sessions from the existing trusted directory."""
import json
import re
from datetime import datetime, timedelta
from hmac import compare_digest

from django.utils import timezone

from apps.editorial_workbench.reviewer_access import browser_proof
from apps.mufti_review.identity import (
    IdentityUnavailable,
    MuftiIdentityProvider,
    require_provider,
    resolve_identity,
    validate_identity,
)

COOKIE = "fatwa_casework_staff"
SALT = "fatwa.casework.staff.v1"
TTL = 15 * 60
HEX = re.compile(r"[a-f0-9]{64}")


class RequestDirectory(MuftiIdentityProvider):
    """Bind every core re-resolution to this browser request's authenticated epoch."""

    def __init__(self, provider, authenticated, *, authenticated_provider_id):
        require_provider(provider)
        validate_identity(authenticated)
        if provider.provider_id != authenticated_provider_id:
            raise IdentityUnavailable("request_identity_changed")
        self.provider_id = authenticated_provider_id
        self._provider = provider
        self._subject = authenticated.subject_id
        self._epoch = authenticated.auth_epoch

    def authenticate(self, credential):
        raise IdentityUnavailable("request_directory_cannot_authenticate")

    def projection_epoch(self):
        """Optional pure identity revision for composed readers that require it."""
        method = getattr(self._provider, "projection_epoch", None)
        if not callable(method) or self._provider.provider_id != self.provider_id:
            raise IdentityUnavailable("request_identity_snapshot_required")
        epoch = method()
        if type(epoch) is not str or not 1 <= len(epoch) <= 65536:
            raise IdentityUnavailable("request_identity_snapshot_required")
        return repr((id(self._provider), self.provider_id, self._subject, self._epoch, epoch))

    def resolve(self, subject_id):
        if subject_id != self._subject or self._provider.provider_id != self.provider_id:
            raise IdentityUnavailable("request_identity_changed")
        identity = resolve_identity(self._provider, subject_id)
        if identity.auth_epoch != self._epoch or self._provider.provider_id != self.provider_id:
            raise IdentityUnavailable("request_identity_changed")
        return identity


def _binding(request, provider, subject, epoch, until):
    return browser_proof(
        request, SALT, json.dumps([provider, subject, epoch, until], separators=(",", ":"))
    )


def set_staff_cookie(request, response, provider, identity):
    validate_identity(identity)
    until = min(identity.valid_until, timezone.now() + timedelta(seconds=TTL)).isoformat()
    values = {
        "provider": provider.provider_id,
        "subject": identity.subject_id,
        "epoch": identity.auth_epoch,
        "until": until,
        "binding": _binding(
            request, provider.provider_id, identity.subject_id, identity.auth_epoch, until
        ),
    }
    response.set_signed_cookie(
        COOKIE, json.dumps(values, separators=(",", ":")), salt=SALT, max_age=TTL,
        httponly=True, samesite="Strict", path="/casework/", secure=False,
    )
    return response


def current_staff(request, provider, *, case_key=None):
    saved = request.get_signed_cookie(COOKIE, default="", salt=SALT, max_age=TTL)
    try:
        if type(saved) is not str or not 1 <= len(saved) <= 2048:
            raise ValueError("missing_cookie")
        values = json.loads(saved)
        if (
            type(values) is not dict
            or set(values) != {"provider", "subject", "epoch", "until", "binding"}
            or any(type(value) is not str for value in values.values())
            or HEX.fullmatch(values["binding"]) is None
        ):
            raise ValueError("invalid_cookie")
        until = datetime.fromisoformat(values["until"])
        if (
            not timezone.is_aware(until) or until.utcoffset() != timedelta(0)
            or until <= timezone.now()
        ):
            raise ValueError("expired_cookie")
        identity = resolve_identity(provider, values["subject"], case_key=case_key)
        if values["provider"] != provider.provider_id or values["epoch"] != identity.auth_epoch:
            raise ValueError("identity_changed")
        expected = _binding(
            request, values["provider"], values["subject"], values["epoch"], values["until"]
        )
        if not compare_digest(expected, values["binding"]):
            raise ValueError("browser_binding_missing")
        return identity
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise IdentityUnavailable("casework_session_not_authorized") from exc
