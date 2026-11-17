"""Independent offline provider fixture. Ephemeral keys; no transport or real signer.

Only use in an owned synthetic database. The simulated provider can sign its own
reported outcomes, never a human scholarly decision or return approval.
"""

import base64
import secrets
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.utils import timezone

from apps.answer_media.models import AnswerPart
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent
from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    SignedProviderEvent,
    provider_signing_payload,
)

from .models import CompositeDelivery
from .services import SIMULATOR_PROVIDER, _enabled


class OfflineProviderSimulator:
    def __init__(self, *, synthetic_fixtures_only=False):
        _enabled()
        if synthetic_fixtures_only is not True:
            raise queue.QueueConflict("simulator_synthetic_ack_required")
        queue._postgres_only()
        self._key = Ed25519PrivateKey.generate()
        self.verifier = Ed25519ProviderEventVerifier(
            issuer="offline-composite-fixture",
            audience="synthetic-composite-delivery",
            provider=SIMULATOR_PROVIDER,
            trusted_public_keys={"ephemeral-fixture": self._key.public_key().public_bytes_raw()},
        )

    def event(self, *, lease, part, reported):
        """Sign a fixture outcome for the exact resolved part; does not record/send."""
        _enabled()
        queue._postgres_only()
        intent = DeliveryIntent.objects.get(pk=lease.intent_key)
        queue._authenticate_attempt(intent, lease)
        binding = CompositeDelivery.objects.select_related("decision").get(approval=intent.approval)
        canonical = AnswerPart.objects.get(
            manifest_id=binding.decision.answer_id,
            ordinal=intent.ordinal,
        )
        if (
            str(canonical.pk) != part["id"]
            or canonical.sha256 != part["sha256"]
            or canonical.size != part["size"]
            or canonical.kind != part["kind"]
            or canonical.media_type != part["media_type"]
            or intent.provider != SIMULATOR_PROVIDER
            or intent.ordinal != part["ordinal"]
            or intent.payload_sha256 != part["envelope_sha256"]
            or sha256(part["raw"]).hexdigest() != part["sha256"]
            or len(part["raw"]) != part["size"]
            or reported not in {"ACCEPTED", "DELIVERED", "FAILED"}
        ):
            raise queue.QueueConflict("simulator_part_or_outcome_mismatch")
        now = timezone.now()
        event = SignedProviderEvent(
            issuer="offline-composite-fixture",
            audience="synthetic-composite-delivery",
            key_id="ephemeral-fixture",
            provider=SIMULATOR_PROVIDER,
            plan_fingerprint=intent.plan_fingerprint,
            intent_key=intent.pk,
            ordinal=intent.ordinal,
            part_digest=intent.payload_sha256,
            attempt_sha256=sha256(lease.token.encode()).hexdigest(),
            receipt_reference="sim-" + secrets.token_hex(16),
            provider_message_id="sim-message-" + intent.pk,
            reported=reported,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
            signature_b64url="",
        )
        return replace(
            event,
            signature_b64url=base64.urlsafe_b64encode(
                self._key.sign(provider_signing_payload(event)),
            )
            .decode()
            .rstrip("="),
        )
