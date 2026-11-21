"""Immutable authentication evidence; none of these rows grants a domain role."""

from django.db import models
from django.db.models import Q

from apps.staff_sessions.models import Sealed


class Account(Sealed):
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("provider_id", "subject_id"), name="mfa_account_owner")
        ]


class Challenge(Sealed):
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    factor = models.ForeignKey(
        "Factor", on_delete=models.PROTECT, null=True, related_name="challenges"
    )
    factor_digest = models.CharField(max_length=64, blank=True)
    role = models.CharField(max_length=32)
    auth_epoch = models.CharField(max_length=64)
    surface = models.CharField(max_length=16)
    purpose = models.CharField(max_length=16)
    claims_digest = models.CharField(max_length=64)
    browser_digest = models.CharField(max_length=64)
    authority_digest = models.CharField(max_length=64)
    directory_digest = models.CharField(max_length=64)
    runtime_digest = models.CharField(max_length=64)
    key_digest = models.CharField(max_length=64)
    rule_payload = models.TextField()
    nonce_digest = models.CharField(max_length=64)
    primary_method = models.CharField(max_length=128)
    primary_verified_at = models.DateTimeField()
    actor_deadline = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=("LOGIN", "REVOKE")), name="mfa_challenge_purpose"
            ),
            models.CheckConstraint(
                condition=Q(surface__in=("CASEWORK", "OPERATIONS")), name="mfa_challenge_surface"
            ),
        ]


class Factor(Sealed):
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="factors")
    challenge = models.OneToOneField(Challenge, on_delete=models.PROTECT, related_name="enrollment")
    secret_ciphertext = models.TextField()
    secret_binding = models.CharField(max_length=64)
    key_digest = models.CharField(max_length=64)
    runtime_digest = models.CharField(max_length=64)
    algorithm = models.CharField(max_length=8)
    digits = models.PositiveSmallIntegerField()
    period = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(algorithm__in=("SHA1", "SHA256", "SHA512")), name="mfa_factor_algorithm"
            ),
            models.CheckConstraint(condition=Q(digits__in=(6, 8)), name="mfa_factor_digits"),
            models.CheckConstraint(condition=Q(period__in=(30, 60)), name="mfa_factor_period"),
        ]


class Proof(Sealed):
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    factor = models.ForeignKey(Factor, on_delete=models.PROTECT, related_name="proofs")
    challenge = models.OneToOneField(Challenge, on_delete=models.PROTECT, related_name="proof")
    purpose = models.CharField(max_length=16)
    counter = models.PositiveBigIntegerField()
    verified_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=("ENROLL", "LOGIN", "REVOKE")), name="mfa_proof_purpose"
            ),
            models.UniqueConstraint(fields=("factor", "counter"), name="mfa_one_use_counter"),
            models.UniqueConstraint(
                fields=("factor",), condition=Q(purpose="ENROLL"), name="mfa_one_activation"
            ),
        ]


class Attempt(Sealed):
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    challenge = models.ForeignKey(Challenge, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    accepted = models.BooleanField()

    class Meta:
        indexes = [models.Index(fields=("account", "created_at"), name="mfa_attempt_account")]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("OTP", "RECOVERY")), name="mfa_attempt_kind"
            )
        ]


class RecoveryCode(Sealed):
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    factor = models.ForeignKey(Factor, on_delete=models.PROTECT, related_name="recovery_codes")
    activation = models.ForeignKey(Proof, on_delete=models.PROTECT)
    slot = models.PositiveSmallIntegerField()
    code_digest = models.CharField(max_length=64, unique=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("factor", "slot"), name="mfa_recovery_slot")]


class FactorRevocation(Sealed):
    factor = models.OneToOneField(Factor, on_delete=models.PROTECT, related_name="revocation")
    challenge = models.ForeignKey(Challenge, on_delete=models.PROTECT)
    proof = models.OneToOneField(Proof, on_delete=models.PROTECT, null=True)
    recovery_code = models.ForeignKey(RecoveryCode, on_delete=models.PROTECT, null=True)
    reason = models.CharField(max_length=16)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(reason="USER_REVOKE", proof__isnull=False, recovery_code__isnull=True)
                    | Q(reason="RECOVERY", proof__isnull=True, recovery_code__isnull=False)
                ),
                name="mfa_revocation_cause",
            )
        ]


class RecoveryUse(Sealed):
    code = models.OneToOneField(RecoveryCode, on_delete=models.PROTECT, related_name="consumption")
    challenge = models.OneToOneField(Challenge, on_delete=models.PROTECT, related_name="recovery")
    revocation = models.ForeignKey(FactorRevocation, on_delete=models.PROTECT)


class SessionAssurance(Sealed):
    session = models.OneToOneField(
        "staff_sessions.Session", on_delete=models.PROTECT, related_name="mfa_assurance"
    )
    proof = models.OneToOneField(Proof, on_delete=models.PROTECT, related_name="assurance")
    expires_at = models.DateTimeField()
