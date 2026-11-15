"""PostgreSQL-only synthetic delivery queue; never wired to a real sender."""
from django.db import models
from django.db.models import Q, F


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
    STATES = [(x, x) for x in (
        STAGED, LEASED, SENT_UNCONFIRMED, DELIVERED,
        FAILED_REQUIRES_REVIEW, UNKNOWN_REQUIRES_RECONCILIATION,
    )]

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
            models.CheckConstraint(
                condition=(
                    Q(state=STAGED, lease_token_sha256__isnull=True, lease_owner__isnull=True,
                      lease_expires_at__isnull=True, provider_message_id__isnull=True, provider_status__isnull=True)
                    | Q(state=LEASED, lease_token_sha256__regex=r"^[a-f0-9]{64}$",
                        lease_owner__isnull=False, lease_expires_at__isnull=False,
                        provider_message_id__isnull=True, provider_status__isnull=True)
                    | Q(state=SENT_UNCONFIRMED, lease_token_sha256__isnull=True, lease_owner__isnull=True,
                        lease_expires_at__isnull=True, provider_message_id__isnull=False, provider_status="ACCEPTED")
                    | Q(state=DELIVERED, lease_token_sha256__isnull=True, lease_owner__isnull=True,
                        lease_expires_at__isnull=True, provider_message_id__isnull=False, provider_status="DELIVERED")
                    | Q(state=FAILED_REQUIRES_REVIEW, lease_token_sha256__isnull=True, lease_owner__isnull=True,
                        lease_expires_at__isnull=True, provider_message_id__isnull=False, provider_status="FAILED")
                    | Q(state=UNKNOWN_REQUIRES_RECONCILIATION, lease_token_sha256__regex=r"^[a-f0-9]{64}$",
                        lease_owner__isnull=False, lease_expires_at__isnull=False,
                        provider_message_id__isnull=True, provider_status__isnull=True)
                ),
                name="dq_intent_state_consistent",
            ),
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


class DeliveryAuditEvent(models.Model):
    intent = models.ForeignKey(DeliveryIntent, on_delete=models.PROTECT, related_name="audit_events")
    old_state = models.CharField(max_length=40)
    new_state = models.CharField(max_length=40)
    event_reference = models.CharField(max_length=128)
    event_payload_sha256 = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fatwa_delivery_audit_event"
        ordering = ["id"]
