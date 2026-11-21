"""Stable independent destinations and append-only exact-copy history."""

import uuid

from django.db import models
from django.db.models import Q

COMMANDS = ("REVIEW", "APPROVE", "PREPARE", "ACCEPTED", "SIMULATED_PUBLISHED", "FAILED", "WITHDRAW")


class DestinationRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    destination = models.CharField(max_length=24)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("case", "destination"), name="pd_record_destination"),
            models.CheckConstraint(
                condition=Q(destination__in=("WEBSITE", "TELEGRAM_CHANNEL")), name="pd_record_kind"
            ),
        ]


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    request_key = models.UUIDField(unique=True)
    request_sha256 = models.CharField(max_length=64)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    note = models.CharField(max_length=1000)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class DestinationVersion(Sealed):
    record = models.ForeignKey(DestinationRecord, related_name="versions", on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    source = models.ForeignKey(
        "experimental_publication.PublicationEdition", on_delete=models.PROTECT
    )
    source_pins = models.JSONField(default=dict)
    profile_payload = models.TextField()
    profile_sha256 = models.CharField(max_length=64)
    plan_payload = models.TextField()
    plan_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("record", "number"), name="pd_version_number"),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="pd_version_bound"
            ),
        ]


class DestinationEvent(Sealed):
    version = models.ForeignKey(DestinationVersion, related_name="events", on_delete=models.PROTECT)
    sequence = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    action = models.CharField(max_length=24)
    plan_sha256 = models.CharField(max_length=64)
    valid_until = models.DateTimeField(null=True)
    provider_event_id = models.UUIDField(null=True, unique=True)
    provider_envelope = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("version", "sequence"), name="pd_event_sequence"),
            models.UniqueConstraint(fields=("version", "action"), name="pd_event_once"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=6), name="pd_event_bound"
            ),
            models.CheckConstraint(condition=Q(action__in=COMMANDS), name="pd_event_kind"),
            models.CheckConstraint(
                condition=Q(action="PREPARE", valid_until__isnull=False)
                | (~Q(action="PREPARE") & Q(valid_until__isnull=True)),
                name="pd_event_deadline",
            ),
            models.CheckConstraint(
                condition=Q(
                    action__in=("ACCEPTED", "SIMULATED_PUBLISHED", "FAILED"),
                    provider_event_id__isnull=False,
                )
                | (
                    ~Q(action__in=("ACCEPTED", "SIMULATED_PUBLISHED", "FAILED"))
                    & Q(provider_event_id__isnull=True, provider_envelope={})
                ),
                name="pd_provider_event_scope",
            ),
        ]
