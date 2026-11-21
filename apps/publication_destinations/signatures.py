"""Offline simulator outcomes reuse the reviewed Ed25519 receipt verifier.

Domain separation and a complete typed scope hash bind the publication version.
No delivery intent/receipt is written and a signature is not external availability.
"""

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    SignedProviderEvent,
    provider_signing_payload,
)

from .profiles import fingerprint

AUDIENCE = "synthetic-destination-publication"
PROVIDER = "publication-simulator"


@dataclass(frozen=True, slots=True)
class SignedDestinationOutcome:
    issuer: str
    audience: str
    key_id: str
    provider: str
    event_id: str
    record_id: str
    version_id: str
    version_sha256: str
    preparation_id: str
    preparation_sha256: str
    destination: str
    profile_sha256: str
    plan_sha256: str
    source_id: str
    source_sha256: str
    reported: str
    issued_at: str
    expires_at: str
    signature_b64url: str


def adapt(event):
    if not isinstance(event, SignedDestinationOutcome):
        raise ValueError("destination_signed_outcome_required")
    for name in ("event_id", "record_id", "version_id", "preparation_id", "source_id"):
        value = getattr(event, name)
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError("destination_outcome_uuid_invalid")
    for name in (
        "version_sha256",
        "preparation_sha256",
        "profile_sha256",
        "plan_sha256",
        "source_sha256",
    ):
        value = getattr(event, name)
        if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
            raise ValueError("destination_outcome_digest_invalid")
    if (
        event.audience != AUDIENCE
        or event.provider != PROVIDER
        or event.destination not in ("WEBSITE", "TELEGRAM_CHANNEL")
        or event.reported not in ("ACCEPTED", "PUBLISHED", "FAILED")
    ):
        raise ValueError("destination_outcome_scope_invalid")
    body = asdict(event)
    body.pop("signature_b64url")
    return SignedProviderEvent(
        issuer=event.issuer,
        audience=AUDIENCE,
        key_id=event.key_id,
        provider=PROVIDER,
        plan_fingerprint=event.plan_sha256,
        intent_key=event.version_sha256,
        ordinal=1,
        part_digest=fingerprint(body),
        attempt_sha256=event.profile_sha256,
        receipt_reference=event.event_id,
        provider_message_id=event.destination,
        reported={"PUBLISHED": "DELIVERED"}.get(event.reported, event.reported),
        issued_at=event.issued_at,
        expires_at=event.expires_at,
        signature_b64url=event.signature_b64url,
    )


def signing_payload(event):
    """Fixture/provider interface only; browser input has no signing capability."""
    return provider_signing_payload(adapt(event))


class DestinationOutcomeVerifier(Ed25519ProviderEventVerifier):
    def __init__(self, *, issuer, trusted_public_keys, revoked_key_ids=frozenset(), clock=None):
        super().__init__(
            issuer=issuer,
            audience=AUDIENCE,
            provider=PROVIDER,
            trusted_public_keys=trusted_public_keys,
            revoked_key_ids=revoked_key_ids,
            clock=clock,
            max_age=timedelta(minutes=15),
            max_lifetime=timedelta(minutes=15),
        )

    def projection_epoch(self):
        # No opaque key-status callback can evade the final pure pin.
        if self._key_status is not None:
            raise ValueError("destination_opaque_key_status_disallowed")
        return repr(
            (
                self._issuer,
                self._audience,
                self._provider,
                sorted(
                    (key, value.public_bytes(Encoding.Raw, PublicFormat.Raw))
                    for key, value in self._keys.items()
                ),
                sorted(self._revoked_ids),
                self._max_age,
                self._max_lifetime,
                id(self._clock),
            )
        )

    def verify(self, event, *, at=None):
        try:
            adapted = adapt(event)
        except (ValueError, TypeError, AttributeError):
            return False
        return super().__call__(adapted, at=at) is True
