"""Synthetic PostgreSQL delivery metadata; no answer bodies or signing keys."""
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ApprovalClaim(models.Model):
    receipt_id = models.CharField(max_length=128, primary_key=True)
    nonce_digest = models.CharField(max_length=64, unique=True)
    approval_fingerprint = models.CharField(max_length=64)
    plan_fingerprint = models.CharField(max_length=64, unique=True)
    case_key = models.CharField(max_length=128)
    answer_revision = models.PositiveIntegerField()
    expected_parts = models.PositiveSmallIntegerField()
    parts_manifest_sha256 = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_delivery_approval_claim"
        constraints = [
            models.CheckConstraint(condition=Q(answer_revision__gte=1), name="dq_claim_revision_positive"),
            models.CheckConstraint(condition=Q(expected_parts__gte=1, expected_parts__lte=16), name="dq_claim_parts_bound"),
        ]


class DeliveryIntent(models.Model):
    STAGED = "STAGED"
    LEASED = "LEASED"
    SENT_UNCONFIRMED = "SENT_UNCONFIRMED"
    DELIVERED = "DELIVERED"
    FAILED_REQUIRES_REVIEW = "FAILED_REQUIRES_REVIEW"
    UNKNOWN_REQUIRES_RECONCILIATION = "UNKNOWN_REQUIRES_RECONCILIATION"
    STATES = [(x, x) for x in (STAGED, LEASED, SENT_UNCONFIRMED, DELIVERED,
                             FAILED_REQUIRES_REVIEW, UNKNOWN_REQUIRES_RECONCILIATION)]
    intent_key = models.CharField(max_length=64, primary_key=True)
    approval = models.ForeignKey(ApprovalClaim, on_delete=models.PROTECT, related_name="intents")
    plan_fingerprint = models.CharField(max_length=64)
    case_key = models.CharField(max_length=128)
    provider = models.CharField(max_length=64)
    answer_revision = models.PositiveIntegerField()
    ordinal = models.PositiveSmallIntegerField()
    payload_sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=40, choices=STATES, default=STAGED)
    lease_token_sha256 = models.CharField(max_length=64, null=True, blank=True)
    lease_owner = models.CharField(max_length=128, null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=128, null=True, blank=True)
    provider_status = models.CharField(max_length=16, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fatwa_delivery_intent"
        ordering = ["case_key", "answer_revision", "ordinal"]
        indexes = [models.Index(fields=["provider", "state", "created_at"], name="dq_intent_claim_idx")]
        constraints = [
            models.UniqueConstraint(fields=["approval", "ordinal"], name="dq_intent_approval_ordinal_unique"),
            models.CheckConstraint(condition=Q(answer_revision__gte=1, ordinal__gte=1, ordinal__lte=16), name="dq_intent_order_bound"),
            models.CheckConstraint(condition=Q(payload_sha256__regex=r"^[a-f0-9]{64}$"), name="dq_intent_payload_sha_format"),
            models.CheckConstraint(condition=Q(plan_fingerprint__regex=r"^[a-f0-9]{64}$"), name="dq_intent_plan_sha_format"),
            models.CheckConstraint(condition=(
                Q(state="STAGED", lease_token_sha256__isnull=True, lease_owner__isnull=True,
                  lease_expires_at__isnull=True, provider_message_id__isnull=True, provider_status__isnull=True)
                | Q(state="LEASED", lease_token_sha256__regex=r"^[a-f0-9]{64}$", lease_owner__isnull=False,
                    lease_expires_at__isnull=False, provider_message_id__isnull=True, provider_status__isnull=True)
                | Q(state="SENT_UNCONFIRMED", lease_token_sha256__isnull=True, lease_owner__isnull=True,
                    lease_expires_at__isnull=True, provider_message_id__isnull=False, provider_status="ACCEPTED")
                | Q(state="DELIVERED", lease_token_sha256__isnull=True, lease_owner__isnull=True,
                    lease_expires_at__isnull=True, provider_message_id__isnull=False, provider_status="DELIVERED")
                | Q(state="FAILED_REQUIRES_REVIEW", lease_token_sha256__isnull=True, lease_owner__isnull=True,
                    lease_expires_at__isnull=True, provider_message_id__isnull=False, provider_status="FAILED")
                | Q(state="UNKNOWN_REQUIRES_RECONCILIATION", lease_token_sha256__regex=r"^[a-f0-9]{64}$",
                    lease_owner__isnull=False, lease_expires_at__isnull=False, provider_message_id__isnull=True,
                    provider_status__isnull=True)
            ), name="dq_intent_state_consistent"),
            # SQL CHECK accepts UNKNOWN. Explicit nullability below closes the
            # gap left by regex/equality predicates on nullable state fields.
            models.CheckConstraint(condition=(
                Q(state="STAGED")
                | Q(state__in=["LEASED", "UNKNOWN_REQUIRES_RECONCILIATION"],
                    lease_token_sha256__isnull=False)
                | Q(state__in=["SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW"],
                    provider_status__isnull=False)
            ), name="dq_intent_required_state_fields"),
        ]


class ProviderReceipt(models.Model):
    receipt_reference = models.CharField(max_length=128, primary_key=True)
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="receipts")
    provider_message_id = models.CharField(max_length=128)
    reported = models.CharField(max_length=16)
    payload_sha256 = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_delivery_provider_receipt"
        constraints = [
            models.CheckConstraint(condition=Q(reported__in=["ACCEPTED", "DELIVERED", "FAILED"]), name="dq_receipt_reported_valid"),
            models.CheckConstraint(condition=Q(payload_sha256__regex=r"^[a-f0-9]{64}$"), name="dq_receipt_payload_sha_format"),
        ]


class DeliveryAuditHead(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True)
    sequence = models.PositiveBigIntegerField(default=0)
    digest = models.CharField(max_length=64, default="")

    class Meta:
        db_table = "fatwa_delivery_audit_head"


class DeliveryAuditEvent(models.Model):
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="audit_events")
    sequence = models.PositiveBigIntegerField(unique=True)
    previous_digest = models.CharField(max_length=64, default="")
    digest = models.CharField(max_length=64, default="")
    old_state = models.CharField(max_length=40)
    new_state = models.CharField(max_length=40)
    event_reference = models.CharField(max_length=128)
    event_payload_sha256 = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "fatwa_delivery_audit_event"
        ordering = ["id"]


class SignedDeliveryContext(models.Model):
    approval = models.OneToOneField(ApprovalClaim, primary_key=True, on_delete=models.PROTECT, related_name="signed_context")
    envelope = models.JSONField()
    envelope_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_delivery_signed_context"


class DeliveryAttempt(models.Model):
    intent = models.OneToOneField(DeliveryIntent, primary_key=True, on_delete=models.PROTECT, related_name="attempt")
    worker_id = models.CharField(max_length=128)
    token_sha256 = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_delivery_attempt"


class ProviderSignatureEvidence(models.Model):
    """Immutable signed provider statement, never a private signing key."""

    receipt = models.OneToOneField(
        ProviderReceipt, on_delete=models.PROTECT, primary_key=True,
        related_name="signature_evidence",
    )
    envelope = models.JSONField()
    envelope_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_delivery_provider_signature_evidence"
        constraints = [
            models.CheckConstraint(
                condition=Q(envelope_sha256__regex=r"^[a-f0-9]{64}$"),
                name="dq_provider_sig_sha_format",
            ),
        ]


class RequesterTrackingCase(models.Model):
    """Synthetic multi-case lifecycle; never stores question or answer content."""

    STAGES = [
        (value, value) for value in (
            "RECEIVED", "UNDER_REVIEW", "NEEDS_CLARIFICATION",
            "WITH_MUFTI", "RETURNED_FOR_CHANGES",
        )
    ]
    case_key = models.CharField(max_length=128, primary_key=True)
    stage = models.CharField(max_length=40, choices=STAGES, default="RECEIVED")
    revision = models.PositiveIntegerField(default=1)
    registered_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fatwa_requester_tracking_case"
        constraints = [
            models.CheckConstraint(condition=Q(revision__gte=1), name="dq_track_revision_positive"),
            models.CheckConstraint(
                condition=Q(stage__in=[key for key, _ in STAGES]),
                name="dq_track_stage_valid",
            ),
        ]


class RequesterTrackingToken(models.Model):
    """Store SHA-256 only; plaintext tracking ticket is returned once."""

    token_sha256 = models.CharField(max_length=64, primary_key=True)
    case = models.ForeignKey(
        RequesterTrackingCase, on_delete=models.PROTECT, related_name="tokens",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fatwa_requester_tracking_token"
        constraints = [
            models.UniqueConstraint(
                fields=["case"], condition=Q(revoked_at__isnull=True),
                name="dq_tracking_one_active_token",
            ),
            models.CheckConstraint(
                condition=Q(token_sha256__regex=r"^[a-f0-9]{64}$"),
                name="dq_tracking_token_hash_format",
            ),
        ]


class RequesterTrackingEvent(models.Model):
    """Append-only history of operational stages, not scholarly decisions."""

    case = models.ForeignKey(
        RequesterTrackingCase, on_delete=models.PROTECT, related_name="events",
    )
    sequence = models.PositiveIntegerField()
    old_stage = models.CharField(max_length=40)
    new_stage = models.CharField(max_length=40)
    actor_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_requester_tracking_event"
        constraints = [
            models.UniqueConstraint(
                fields=["case", "sequence"],
                name="dq_tracking_event_sequence_unique",
            ),
        ]
