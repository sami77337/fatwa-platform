"""Ephemeral TEST authorities for a local human-operated drill; never application defaults."""

import base64
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import timedelta
from threading import RLock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.db import connection
from django.utils import timezone

from apps.casework import services as cases
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.trusted_identity import (
    Ed25519ApprovalVerifier,
    IdentityStatus,
    SignedApprovalReceipt,
    approval_signing_payload,
)
from apps.mufti_review.identity import IdentityUnavailable, require_provider, resolve_identity

MAX_ISSUED = 64
MAX_LEASES = 32


class FixtureOperatorAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Literal True for OPEN, AUTHORIZE_RETURN, REPORT_PROVIDER; never role alone."""
        raise NotImplementedError


class _ReturnPermissionFixture:
    """Private implementation: only a current locked pilot action can issue a receipt."""

    def __init__(self, fixture):
        self._fixture = fixture
        self._key = Ed25519PrivateKey.generate()
        self._issued = {}
        self.verifier = Ed25519ApprovalVerifier(
            issuer="synthetic-pilot-return-fixture",
            audience="synthetic-pilot-composite",
            trusted_public_keys={"ephemeral-pilot": self._key.public_key().public_bytes_raw()},
            identity_lookup=self._identity,
            is_revoked_or_consumed=self._revoked,
        )

    def _identity(self, subject):
        try:
            actor = resolve_identity(self._fixture.identity_provider, subject)
            return IdentityStatus(actor.subject_id, actor.role, actor.active)
        except IdentityUnavailable:
            return None

    def _revoked(self, receipt_id, nonce, key_id):
        entry = self._issued.get(receipt_id)
        if entry is None or key_id != "ephemeral-pilot" or nonce != entry[0]:
            return True
        _, provider_id, subject, epoch, case_ref = entry
        try:
            actor = resolve_identity(self._fixture.identity_provider, subject, case_key=case_ref)
            return (
                timezone.now() >= self._fixture.expires_at
                or provider_id != self._fixture.identity_provider.provider_id
                or actor.auth_epoch != epoch
                or self._fixture.operator_authority.permits(
                    provider_id=provider_id,
                    subject_id=subject,
                    auth_epoch=epoch,
                    case_ref=case_ref,
                    action="AUTHORIZE_RETURN",
                )
                is not True
            )
        except Exception:
            return True

    def _issue_locked(self, prepared, actor, provider_id):
        # Never sign a caller-supplied arbitrary payload, even through this internal helper.
        from apps.casework.models import CaseDecision
        from apps.composite_delivery.services import prepare_composite_delivery

        if not connection.in_atomic_block:
            raise cases.CaseConflict("pilot_locked_canonical_permission_required")
        decision = (
            CaseDecision.objects.select_related("case")
            .filter(pk=prepared.get("decision_id"))
            .first()
        )
        if decision is None or provider_id != self._fixture.identity_provider.provider_id:
            raise cases.CaseConflict("pilot_canonical_permission_required")
        current = resolve_identity(
            self._fixture.identity_provider, actor.subject_id, case_key=decision.case.public_ref
        )
        fresh = prepare_composite_delivery(
            case_id=decision.case_id,
            subject_id=actor.subject_id,
            provider=self._fixture.identity_provider,
            synthetic_fixtures_only=True,
        )
        if (
            current != actor
            or fresh != prepared
            or self._fixture.operator_authority.permits(
                provider_id=provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                case_ref=decision.case.public_ref,
                action="AUTHORIZE_RETURN",
            )
            is not True
        ):
            raise cases.CaseConflict("pilot_canonical_permission_changed")
        if len(self._issued) >= MAX_ISSUED:
            raise cases.CaseConflict("pilot_permission_capacity")
        now = timezone.now()
        evidence = prepared["evidence"]
        receipt = SignedApprovalReceipt(
            **{
                name: evidence[name]
                for name in (
                    "case_key",
                    "answer_revision",
                    "answer_sha256",
                    "source_digest",
                    "reply_digest",
                )
            },
            approver_id=actor.subject_id,
            approver_role="MUFTI",
            decision="APPROVE_RETURN_TO_ORIGIN",
            receipt_id="pilot-" + secrets.token_hex(16),
            issued_at=now.isoformat(),
            expires_at=min(
                now + timedelta(minutes=4), actor.valid_until, self._fixture.expires_at
            ).isoformat(),
            issuer="synthetic-pilot-return-fixture",
            audience="synthetic-pilot-composite",
            key_id="ephemeral-pilot",
            nonce=secrets.token_urlsafe(32),
            plan_sha256=prepared["plan_sha256"],
            signature_b64url="",
        )
        receipt = replace(
            receipt,
            signature_b64url=base64.urlsafe_b64encode(
                self._key.sign(approval_signing_payload(receipt))
            )
            .decode()
            .rstrip("="),
        )
        self._issued[receipt.receipt_id] = (
            receipt.nonce,
            provider_id,
            actor.subject_id,
            actor.auth_epoch,
            evidence["case_key"],
        )
        return receipt


class PilotFixture:
    """Two separate fixture authorities plus bounded existing worker-lease memory.

    This cache contains no queue state. PostgreSQL remains authoritative. Lost
    memory never reconstructs a lease, reserves a replacement or resumes a sender.
    """

    def __init__(self, *, operator_authority, identity_provider, synthetic_fixtures_only=False):
        if synthetic_fixtures_only is not True or os.environ.get("FATWA_PRODUCTION") != "0":
            raise cases.CaseConflict("pilot_synthetic_bootstrap_required")
        cases._guard(synthetic_fixtures_only)
        from apps.composite_delivery.services import _enabled

        _enabled()
        require_provider(identity_provider)
        if not isinstance(operator_authority, FixtureOperatorAuthority):
            raise cases.CaseConflict("pilot_operator_authority_required")
        self.operator_authority = operator_authority
        self.identity_provider = identity_provider
        self.expires_at = timezone.now() + timedelta(minutes=30)
        self.lock = RLock()
        self._attempts = {}
        self.worker_id = "pilot-worker-" + secrets.token_hex(16)
        self._return_authority = _ReturnPermissionFixture(self)
        self.approval_verifier = self._return_authority.verifier
        self.provider_fixture = OfflineProviderSimulator(synthetic_fixtures_only=True)
        self.provider_verifier = self.provider_fixture.verifier

    def settings(self):
        """Explicit injection only. Does not mutate Django settings or enable other apps."""
        return {
            "FATWA_PILOT_WORKBENCH_ENABLED": True,
            "FATWA_PILOT_WORKBENCH": self,
            "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER": self.approval_verifier,
            "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER": self.provider_verifier,
        }


def setup_synthetic_fixture(
    *, operator_authority, identity_provider, synthetic_fixtures_only=False
):
    return PilotFixture(
        operator_authority=operator_authority,
        identity_provider=identity_provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
