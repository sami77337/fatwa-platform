"""Synthetic end-to-end case/approval/provider evidence, using actual PostgreSQL."""

import base64
import secrets
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.utils import timezone

from apps.casework import delivery as d
from apps.casework import services as s
from apps.delivery_planner.trusted_identity import (
    Ed25519ApprovalVerifier,
    IdentityStatus,
    SignedApprovalReceipt,
    approval_signing_payload,
)
from apps.delivery_queue.models import (
    DeliveryIntent,
)
from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    SignedProviderEvent,
    provider_signing_payload,
)
from tests.casework.test_core import TestDirectory


class CaseDeliveryFixture:
    def setUp(self):
        self.now = timezone.now()
        self.approval_key = Ed25519PrivateKey.generate()
        self.channel_key = Ed25519PrivateKey.generate()
        self.revoked = False
        self.approval_verifier = Ed25519ApprovalVerifier(
            issuer="synthetic-mufti",
            audience="synthetic-case-return",
            trusted_public_keys={"mufti-key": self.approval_key.public_key().public_bytes_raw()},
            identity_lookup=lambda subject: IdentityStatus(subject, "MUFTI", True),
            is_revoked_or_consumed=lambda *_: self.revoked,
            clock=lambda: self.now,
        )
        self.channel_verifier = self.verifier()
        self.a = self.intake("a")
        self.directory = TestDirectory([self.a["public_ref"]])

    def verifier(self, **changes):
        kwargs = dict(
            issuer="synthetic-channel",
            audience="synthetic-case-delivery",
            provider=d.CHANNEL,
            trusted_public_keys={"channel-key": self.channel_key.public_key().public_bytes_raw()},
            clock=lambda: self.now,
        )
        return Ed25519ProviderEventVerifier(**{**kwargs, **changes})

    def intake(self, suffix):
        return s.intake_case(
            original_question="  سؤال اصطناعي حرفي\n" + suffix,
            requester_id="requester-" + suffix,
            source_event_id="website-" + suffix,
            idempotency_key="intake-" + suffix,
            synthetic_fixtures_only=True,
        )

    def staff(self, case=None, **overrides):
        return dict(
            case_id=(case or self.a)["case_id"],
            subject_id="synthetic-mufti",
            provider=overrides.get("provider", self.directory),
            synthetic_fixtures_only=True,
        )

    def approve(self, case=None):
        args = self.staff(case)
        current = s.read_case(**args)
        draft = s.save_answer(
            **args,
            text="  جواب بشري اصطناعي.\nتفصيل محفوظ حرفيًا.  ",
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        return s.record_decision(
            **args,
            answer_id=draft["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=draft["revision"],
            expected_evidence_version=draft["evidence_version"],
        )

    def request(self, case=None):
        return d.prepare_case_delivery(**self.staff(case), max_chars=24, split=True)

    def receipt(self, request, **changes):
        fields = {
            key: request["evidence"][key]
            for key in (
                "case_key",
                "answer_revision",
                "answer_sha256",
                "source_digest",
                "reply_digest",
            )
        }
        fields.update(
            approver_id="synthetic-mufti",
            approver_role="MUFTI",
            decision="APPROVE_RETURN_TO_ORIGIN",
            receipt_id="approval-" + secrets.token_hex(12),
            issued_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(minutes=4)).isoformat(),
            issuer="synthetic-mufti",
            audience="synthetic-case-return",
            key_id="mufti-key",
            nonce=secrets.token_urlsafe(32),
            plan_sha256=request["plan_sha256"],
            signature_b64url="",
        )
        unsigned = SignedApprovalReceipt(**{**fields, **changes})
        return replace(
            unsigned,
            signature_b64url=base64.urlsafe_b64encode(
                self.approval_key.sign(approval_signing_payload(unsigned))
            )
            .decode()
            .rstrip("="),
        )

    def stage(self, case=None, receipt=None, **changes):
        kwargs = dict(
            **self.staff(case),
            receipt=receipt or self.receipt(self.request(case)),
            verify_receipt=self.approval_verifier,
            max_chars=24,
            split=True,
        )
        return d.stage_case_delivery(**{**kwargs, **changes})

    def reserve(self, case=None, **changes):
        kwargs = dict(
            **self.staff(case),
            worker_id="synthetic-worker",
            verify_worker=lambda worker, plan: worker == "synthetic-worker",
            verify_receipt=self.approval_verifier,
        )
        return d.reserve_case_delivery(**{**kwargs, **changes})

    def event(self, lease, **changes):
        intent = DeliveryIntent.objects.get(pk=lease.intent_key)
        fields = dict(
            issuer="synthetic-channel",
            audience="synthetic-case-delivery",
            key_id="channel-key",
            provider=d.CHANNEL,
            plan_fingerprint=intent.plan_fingerprint,
            intent_key=intent.pk,
            ordinal=intent.ordinal,
            part_digest=intent.payload_sha256,
            attempt_sha256=sha256(lease.token.encode()).hexdigest(),
            receipt_reference="provider-" + secrets.token_hex(12),
            provider_message_id="message-" + str(intent.ordinal),
            reported="DELIVERED",
            issued_at=self.now.isoformat(),
            expires_at=(self.now + timedelta(minutes=4)).isoformat(),
            signature_b64url="",
        )
        unsigned = SignedProviderEvent(**{**fields, **changes})
        return replace(
            unsigned,
            signature_b64url=base64.urlsafe_b64encode(
                self.channel_key.sign(provider_signing_payload(unsigned))
            )
            .decode()
            .rstrip("="),
        )

    def record(self, lease, event=None, case=None):
        return d.record_case_provider_event(
            **self.staff(case),
            lease=lease,
            event=event or self.event(lease),
            verifier=self.channel_verifier,
        )

    def status(self, case=None, **changes):
        return d.requester_delivery_status(
            (case or self.a)["token"],
            synthetic_fixtures_only=True,
            verifier=changes.get("verifier", self.channel_verifier),
        )

    def deliver(self, case=None):
        while lease := self.reserve(case):
            self.record(lease, case=case)
