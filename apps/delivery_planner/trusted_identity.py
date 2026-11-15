"""Provider-neutral Ed25519 verifier for signed MUFTI approval receipts."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import re
from typing import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .approval import ApprovalReceipt

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]{86}$")
_CLOCK_SKEW = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class SignedApprovalReceipt(ApprovalReceipt):
    issuer: str
    audience: str
    key_id: str
    expires_at: str
    nonce: str
    signature_b64url: str


@dataclass(frozen=True, slots=True)
class IdentityStatus:
    subject_id: str
    role: str
    active: bool


def approval_signing_payload(receipt: SignedApprovalReceipt) -> bytes:
    """Canonical UTF-8 JSON bytes signed by the trusted identity provider."""
    if not isinstance(receipt, SignedApprovalReceipt):
        raise TypeError("signed_approval_receipt_required")
    claims = {
        "schema": "fatwa.muﬁ.approval.v1",
        "issuer": receipt.issuer,
        "audience": receipt.audience,
        "key_id": receipt.key_id,
        "receipt_id": receipt.receipt_id,
        "case_key": receipt.case_key,
        "answer_revision": receipt.answer_revision,
        "answer_sha256": receipt.answer_sha256,
        "source_digest": receipt.source_digest,
        "reply_digest": receipt.reply_digest,
        "approver_id": receipt.approver_id,
        "approver_role": receipt.approver_role,
        "decision": receipt.decision,
        "issued_at": receipt.issued_at,
        "expires_at": receipt.expires_at,
        "nonce": receipt.nonce,
    }
    return json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc(value: object) -> datetime | None:
    if type(value) is not str or not 20 <= len(value) <= 40:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        return None
    return stamp.astimezone(UTC)


class Ed25519ApprovalVerifier:
    """Fail-closed verifier; all identity and revocation readers are injected."""

    def __init__(
        self, *, issuer: str, audience: str,
        trusted_public_keys: Mapping[str, bytes],
        identity_lookup: Callable[[str], IdentityStatus | None],
        is_revoked_or_consumed: Callable[[str, str, str], bool],
        revoked_key_ids: frozenset[str] = frozenset(),
        clock: Callable[[], datetime] | None = None,
        max_age: timedelta = timedelta(minutes=5),
        max_lifetime: timedelta = timedelta(minutes=10),
    ) -> None:
        if not _ID.fullmatch(issuer) or not _ID.fullmatch(audience):
            raise ValueError("invalid_trust_scope")
        if not trusted_public_keys or not callable(identity_lookup) or not callable(is_revoked_or_consumed):
            raise ValueError("incomplete_trust_configuration")
        self._keys = {}
        for key_id, raw in trusted_public_keys.items():
            if not _ID.fullmatch(key_id) or type(raw) is not bytes or len(raw) != 32:
                raise ValueError("invalid_ed25519_trust_key")
            self._keys[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        if any(not _ID.fullmatch(item) for item in revoked_key_ids):
            raise ValueError("invalid_revoked_key_id")
        if not timedelta(seconds=1) <= max_age <= timedelta(hours=1):
            raise ValueError("invalid_approval_max_age")
        if not timedelta(seconds=1) <= max_lifetime <= timedelta(hours=1):
            raise ValueError("invalid_approval_max_lifetime")
        self._issuer = issuer
        self._audience = audience
        self._identity_lookup = identity_lookup
        self._is_revoked_or_consumed = is_revoked_or_consumed
        self._revoked_key_ids = frozenset(revoked_key_ids)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_age = max_age
        self._max_lifetime = max_lifetime

    def __call__(self, receipt: ApprovalReceipt) -> bool:
        if not isinstance(receipt, SignedApprovalReceipt):
            return False
        if not (
            receipt.issuer == self._issuer
            and receipt.audience == self._audience
            and _ID.fullmatch(receipt.key_id) is not None
            and _ID.fullmatch(receipt.receipt_id) is not None
            and _ID.fullmatch(receipt.approver_id) is not None
            and _NONCE.fullmatch(receipt.nonce) is not None
            and _B64URL.fullmatch(receipt.signature_b64url) is not None
            and receipt.approver_role == "MUFTI"
            and receipt.decision == "APPROVE_RETURN_TO_ORIGIN"
        ):
            return False
        if receipt.key_id in self._revoked_key_ids:
            return False
        key = self._keys.get(receipt.key_id)
        if key is None:
            return False
        issued, expires = _utc(receipt.issued_at), _utc(receipt.expires_at)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("trusted_clock_must_be_utc")
        now = now.astimezone(UTC)
        if issued is None or expires is None or not (
            issued <= now + _CLOCK_SKEW
            and expires > now
            and expires > issued
            and expires - issued <= self._max_lifetime
            and now - issued <= self._max_age + _CLOCK_SKEW
        ):
            return False
        # Verify the signature before making identity-directory or revocation calls.
        try:
            signature = base64.urlsafe_b64decode(receipt.signature_b64url + "==")
            if base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=") != receipt.signature_b64url:
                return False
            key.verify(signature, approval_signing_payload(receipt))
        except (InvalidSignature, ValueError, TypeError):
            return False
        identity = self._identity_lookup(receipt.approver_id)
        if not (
            isinstance(identity, IdentityStatus)
            and identity.subject_id == receipt.approver_id
            and identity.role == "MUFTI"
            and identity.active is True
        ):
            return False
        # Provider lookup failure propagates; require_return_approval fails closed.
        return self._is_revoked_or_consumed(
            receipt.receipt_id, receipt.nonce, receipt.key_id
        ) is False
