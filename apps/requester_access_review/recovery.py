"""Trusted, one-time, tokenless recovery for the isolated synthetic case portal.

The browser's public reference and opaque credential never select the requester.
A server-configured, externally verified identity assertion must bind both the
requester and the exact case. No credential issuer or private key exists here.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
import re

from django.db import transaction
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.models import RequesterTrackingToken

from .models import UsedRecoveryAssertion

_CASE_REF = re.compile(r"FT-[0-9]{4}-[A-F0-9]{20}")
_ASSERTION_ID = re.compile(r"[A-Za-z0-9_-]{32,128}")
_ISSUER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_CREDENTIAL = re.compile(r"[A-Za-z0-9._~-]{32,512}")
_AUDIENCE = "fatwa.casework.private-recovery.v1"
_SKEW = timedelta(seconds=30)
_MAX_LIFETIME = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class VerifiedRecovery:
    """A server-side provider result, never a browser-submitted JSON claim."""

    issuer_id: str
    audience: str
    assertion_id: str
    public_ref: str
    requester_id: str
    issued_at: datetime
    expires_at: datetime


class TrustedRecoveryAuthority(ABC):
    """External identity assurance boundary; the verifier is read-only.

    Implementations MUST independently authenticate proof, validate its signature
    or trusted account verification, and check revocation on every call. The
    application owns one-time consumption, access revocation and audit atomically.
    """

    issuer_id: str

    @abstractmethod
    def verify(self, credential: str, public_ref: str) -> VerifiedRecovery | None:
        raise NotImplementedError


def _valid(attestation, authority, case, now):
    if not isinstance(attestation, VerifiedRecovery):
        return False
    if not (
        type(attestation.issuer_id) is str
        and attestation.issuer_id == authority.issuer_id
        and attestation.audience == _AUDIENCE
        and type(attestation.assertion_id) is str
        and _ASSERTION_ID.fullmatch(attestation.assertion_id) is not None
        and type(attestation.public_ref) is str
        and compare_digest(attestation.public_ref, case.public_ref)
        and type(attestation.requester_id) is str
        and compare_digest(attestation.requester_id, case.requester_id)
        and isinstance(attestation.issued_at, datetime)
        and isinstance(attestation.expires_at, datetime)
    ):
        return False
    issued, expires = attestation.issued_at, attestation.expires_at
    return (
        timezone.is_aware(issued)
        and timezone.is_aware(expires)
        and issued.utcoffset() == timedelta(0)
        and expires.utcoffset() == timedelta(0)
        and issued <= now + _SKEW
        and issued >= now - _MAX_LIFETIME - _SKEW
        and expires > now
        and expires > issued
        and expires - issued <= _MAX_LIFETIME
    )


def recover_lost_access(
    *, public_ref, credential, authority, synthetic_fixtures_only=False
):
    """Atomically consume an independently verified assertion and rotate access.

    Nothing is issued on missing/mismatched/expired/replayed assertions. The
    previous bearer tokens are revoked and the immutable recovery receipt, new
    token and case audit event commit in the SAME PostgreSQL transaction.
    """
    if (
        not isinstance(authority, TrustedRecoveryAuthority)
        or type(getattr(authority, "issuer_id", None)) is not str
        or _ISSUER.fullmatch(authority.issuer_id) is None
    ):
        raise cases.CaseConflict("trusted_recovery_unavailable")
    if (
        type(public_ref) is not str or _CASE_REF.fullmatch(public_ref) is None
        or type(credential) is not str or _CREDENTIAL.fullmatch(credential) is None
    ):
        raise cases.CaseConflict("trusted_recovery_denied")
    cases._guard(synthetic_fixtures_only)
    with transaction.atomic():
        case = Case.objects.select_for_update().filter(public_ref=public_ref).first()
        if case is None:
            raise cases.CaseConflict("trusted_recovery_denied")
        cases._verify(case)
        if case.revision >= cases.MAX_HISTORY:
            raise cases.CaseConflict("trusted_recovery_denied")

        # The verified identity is read only AFTER the case lock, so concurrent
        # revocations and other rotations cannot cross the consumption boundary.
        try:
            attestation = authority.verify(credential, case.public_ref)
        except Exception:
            raise cases.CaseConflict("trusted_recovery_denied") from None
        if not _valid(attestation, authority, case, timezone.now()):
            raise cases.CaseConflict("trusted_recovery_denied")

        fingerprint = sha256(
            (authority.issuer_id + ":" + attestation.assertion_id).encode("ascii")
        ).hexdigest()
        if UsedRecoveryAssertion.objects.filter(pk=fingerprint).exists():
            raise cases.CaseConflict("trusted_recovery_denied")
        UsedRecoveryAssertion.objects.create(
            digest=fingerprint, case=case, issuer_id=authority.issuer_id
        )
        RequesterTrackingToken.objects.filter(
            case_id=case.tracking_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        token = cases._ticket(case)
        cases._event(case, "ROTATE_ACCESS", "recovery:" + authority.issuer_id)
        cases._verify(case)
        return {"public_ref":case.public_ref, "token":token, "rotated":True}
