"""Offline Ed25519 provider event contract; no network sender or key generation."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
import json
import re
from typing import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.db import DatabaseError

from . import services as queue
from .models import DeliveryAttempt, DeliveryIntent, ProviderSignatureEvidence

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_SIG = re.compile(r"^[A-Za-z0-9_-]{86}$")
_SKEW = timedelta(seconds=30)
_SCHEMA = "fatwa.provider-receipt.ed25519.v1"


@dataclass(frozen=True, slots=True)
class SignedProviderEvent:
    issuer: str
    audience: str
    key_id: str
    provider: str
    plan_fingerprint: str
    intent_key: str
    ordinal: int
    part_digest: str
    attempt_sha256: str
    receipt_reference: str
    provider_message_id: str
    reported: str
    issued_at: str
    expires_at: str
    signature_b64url: str


def provider_signing_payload(event: SignedProviderEvent) -> bytes:
    """The exact canonical UTF-8 bytes an external channel issuer signs."""
    if not isinstance(event, SignedProviderEvent):
        raise TypeError("signed_provider_event_required")
    claims = asdict(event)
    claims.pop("signature_b64url")
    claims["schema"] = _SCHEMA
    return json.dumps(
        claims, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _utc(value):
    if type(value) is not str or not 20 <= len(value) <= 40:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        return None
    return stamp.astimezone(UTC)


def _ref(value):
    return type(value) is str and _REF.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


class Ed25519ProviderEventVerifier:
    """Trust keys come solely from reviewed server configuration, never a receipt."""

    def __init__(
        self, *, issuer: str, audience: str, provider: str,
        trusted_public_keys: Mapping[str, bytes],
        revoked_key_ids: frozenset[str] = frozenset(),
        is_key_revoked: Callable[[str], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
        max_age: timedelta = timedelta(minutes=15),
        max_lifetime: timedelta = timedelta(minutes=15),
    ):
        if not all(_ref(item) for item in (issuer, audience, provider)):
            raise ValueError("invalid_provider_trust_scope")
        if not trusted_public_keys:
            raise ValueError("missing_provider_trust_keys")
        keys = {}
        for key_id, raw in trusted_public_keys.items():
            if not _ref(key_id) or type(raw) is not bytes or len(raw) != 32:
                raise ValueError("invalid_provider_trust_key")
            keys[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        if any(not _ref(key_id) for key_id in revoked_key_ids):
            raise ValueError("invalid_revoked_provider_key")
        if is_key_revoked is not None and not callable(is_key_revoked):
            raise ValueError("invalid_provider_key_status_reader")
        if not timedelta(seconds=1) <= max_age <= timedelta(hours=1):
            raise ValueError("invalid_provider_event_max_age")
        if not timedelta(seconds=1) <= max_lifetime <= timedelta(hours=1):
            raise ValueError("invalid_provider_event_lifetime")
        self._keys = keys
        self._revoked_ids = frozenset(revoked_key_ids)
        self._key_status = is_key_revoked
        self._issuer = issuer
        self._audience = audience
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_age = max_age
        self._max_lifetime = max_lifetime

    def __call__(self, event: SignedProviderEvent, *, at: datetime | None = None) -> bool:
        if not isinstance(event, SignedProviderEvent):
            return False
        if not (
            event.issuer == self._issuer
            and event.audience == self._audience
            and event.provider == self._provider
            and all(_ref(value) for value in (
                event.issuer, event.audience, event.provider, event.key_id,
                event.receipt_reference, event.provider_message_id,
            ))
            and all(_sha(value) for value in (
                event.plan_fingerprint, event.intent_key, event.part_digest,
                event.attempt_sha256,
            ))
            and type(event.ordinal) is int and 1 <= event.ordinal <= 16
            and event.reported in ("ACCEPTED", "DELIVERED", "FAILED")
            and type(event.reported) is str
            and type(event.signature_b64url) is str
            and _SIG.fullmatch(event.signature_b64url) is not None
        ):
            return False
        key = self._keys.get(event.key_id)
        if key is None or event.key_id in self._revoked_ids:
            return False
        now = self._clock() if at is None else at
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise queue.QueueConflict("provider_trusted_clock_invalid")
        issued, expires = _utc(event.issued_at), _utc(event.expires_at)
        if issued is None or expires is None or not (
            issued <= now + _SKEW
            and now - issued <= self._max_age + _SKEW
            and expires > now
            and expires > issued
            and expires - issued <= self._max_lifetime
        ):
            return False
        # Signature checking precedes external key-status queries.
        try:
            signature = base64.urlsafe_b64decode(event.signature_b64url + "==")
            if (
                len(signature) != 64
                or base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
                   != event.signature_b64url
            ):
                return False
            key.verify(signature, provider_signing_payload(event))
        except (InvalidSignature, ValueError, TypeError, UnicodeError):
            return False
        if self._key_status is not None:
            try:
                revoked = self._key_status(event.key_id)
            except Exception as exc:
                raise queue.QueueConflict("provider_key_status_unavailable") from exc
            if revoked is not False:
                return False
        return True


def _event_matches_intent(event, lease, intent, attempt):
    if not (
        intent.pk == lease.intent_key == event.intent_key
        and intent.plan_fingerprint == event.plan_fingerprint
        and intent.provider == event.provider
        and intent.ordinal == event.ordinal
        and intent.payload_sha256 == event.part_digest
        and attempt.intent_id == lease.intent_key
        and attempt.worker_id == lease.owner
        and compare_digest(
            attempt.token_sha256, sha256(lease.token.encode("utf-8")).hexdigest()
        )
        and compare_digest(attempt.token_sha256, event.attempt_sha256)
        and attempt.expires_at == lease.expires_at
    ):
        return False
    issued = _utc(event.issued_at)
    return issued is not None and issued >= attempt.created_at - _SKEW


def record_signed_provider_event(*, lease, event, verifier):
    """Reconcile one independently signed event; no dispatch or automatic retry.

    All receipt, immutable signed evidence, state and audit writes are one
    PostgreSQL transaction through queue.record_receipt.
    """
    if not isinstance(lease, queue.WorkerLease) or not isinstance(verifier, Ed25519ProviderEventVerifier):
        raise queue.QueueConflict("trusted_provider_receipt_context_required")
    queue._postgres_only()
    if not verifier(event):
        raise queue.QueueConflict("provider_signature_not_verified")
    try:
        intent = DeliveryIntent.objects.get(pk=lease.intent_key)
        attempt = DeliveryAttempt.objects.get(intent_id=lease.intent_key)
    except (DeliveryIntent.DoesNotExist, DeliveryAttempt.DoesNotExist):
        raise queue.QueueConflict("signed_provider_attempt_missing") from None
    if not _event_matches_intent(event, lease, intent, attempt):
        raise queue.QueueConflict("signed_provider_attempt_or_part_mismatch")

    def verify_again(proof):
        return (
            proof["intent_key"] == event.intent_key
            and proof["receipt_reference"] == event.receipt_reference
            and proof["provider_message_id"] == event.provider_message_id
            and proof["reported"] == event.reported
            and verifier(event) is True
        )

    queue.record_receipt(
        lease=lease,
        receipt_reference=event.receipt_reference,
        provider_message_id=event.provider_message_id,
        reported=event.reported,
        verify_provider_receipt=verify_again,
        signed_evidence=asdict(event),
    )
    return queue.summarize_plan(event.plan_fingerprint)


def verify_stored_provider_evidence(*, receipt_reference, verifier) -> bool:
    """Historical audit: validate original signed statement at recording time."""
    if not _ref(receipt_reference) or not isinstance(verifier, Ed25519ProviderEventVerifier):
        return False
    queue._postgres_only()
    try:
        saved = ProviderSignatureEvidence.objects.select_related(
            "receipt__intent",
        ).get(pk=receipt_reference)
        receipt = saved.receipt
        intent = receipt.intent
        attempt = DeliveryAttempt.objects.get(intent_id=intent.pk)
        evidence = saved.envelope
        if (
            type(evidence) is not dict
            or not compare_digest(
                sha256(queue._canonical(evidence)).hexdigest(),
                saved.envelope_sha256,
            )
        ):
            return False
        event = SignedProviderEvent(**evidence)
        if not verifier(event, at=receipt.recorded_at):
            return False
        if not (
            event.receipt_reference == receipt.pk
            and event.provider_message_id == receipt.provider_message_id
            and event.reported == receipt.reported
            and event.intent_key == intent.pk
            and event.plan_fingerprint == intent.plan_fingerprint
            and event.provider == intent.provider
            and event.ordinal == intent.ordinal
            and event.part_digest == intent.payload_sha256
            and compare_digest(event.attempt_sha256, attempt.token_sha256)
            and (_utc(event.issued_at) or receipt.recorded_at) >= attempt.created_at - _SKEW
        ):
            return False
        payload = json.dumps({
            "intent_key": receipt.intent_id,
            "receipt_reference": receipt.pk,
            "provider_message_id": receipt.provider_message_id,
            "reported": receipt.reported,
        }, sort_keys=True, separators=(",", ":")).encode()
        return compare_digest(receipt.payload_sha256, sha256(payload).hexdigest())
    except (
        ProviderSignatureEvidence.DoesNotExist,
        DeliveryAttempt.DoesNotExist,
        DatabaseError, KeyError, TypeError, ValueError, UnicodeError,
        queue.QueueConflict,
    ):
        return False
