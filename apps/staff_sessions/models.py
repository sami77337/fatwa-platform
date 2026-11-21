"""Append-only authentication history; no row is a permission grant."""

import uuid

from django.db import models
from django.db.models import Q


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Session(Sealed):
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    role = models.CharField(max_length=32)
    auth_epoch = models.CharField(max_length=64)
    surface = models.CharField(max_length=16)
    browser_digest = models.CharField(max_length=64)
    claims_digest = models.CharField(max_length=64)
    runtime_digest = models.CharField(max_length=64)
    authority_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(
                fields=["provider_id", "subject_id", "created_at"], name="staff_session_owner_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(surface__in=("CASEWORK", "OPERATIONS")), name="staff_session_surface"
            ),
            models.CheckConstraint(
                condition=Q(role__in=("MUFTI", "ORGANIZER_ADMIN", "ORGANIZER")),
                name="staff_session_role",
            ),
        ]


class FreshProof(Sealed):
    session = models.ForeignKey(Session, on_delete=models.PROTECT, related_name="proofs")
    target = models.ForeignKey(Session, on_delete=models.PROTECT, related_name="targeted_proofs")
    operation = models.CharField(max_length=32)
    target_digest = models.CharField(max_length=64)
    challenge_digest = models.CharField(max_length=64)
    authority_digest = models.CharField(max_length=64)
    directory_digest = models.CharField(max_length=64)
    method_id = models.CharField(max_length=128)
    verified_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(operation="REVOKE_SESSION"), name="staff_proof_operation"
            )
        ]


class SessionRevocation(Sealed):
    session = models.OneToOneField(Session, on_delete=models.PROTECT, related_name="revocation")
    by_session = models.ForeignKey(
        Session, on_delete=models.PROTECT, related_name="revocations_made"
    )
    reason = models.CharField(max_length=24)
    proof = models.ForeignKey(FreshProof, on_delete=models.PROTECT, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(reason__in=("LOGOUT", "USER_REVOKE")), name="staff_revocation_reason"
            )
        ]


class ProofUse(Sealed):
    proof = models.OneToOneField(FreshProof, on_delete=models.PROTECT, related_name="consumption")
    revocation = models.OneToOneField(
        SessionRevocation, on_delete=models.PROTECT, related_name="proof_use"
    )
