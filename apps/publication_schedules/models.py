import uuid

from django.db import models
from django.db.models import Q


class PublicationSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    edition = models.ForeignKey(
        "experimental_publication.PublicationEdition", on_delete=models.PROTECT
    )
    request_key = models.UUIDField(unique=True)
    edition_sha256 = models.CharField(max_length=64)
    source_sha256 = models.CharField(max_length=64)
    target = models.CharField(max_length=32)
    scheduled_at = models.DateTimeField()
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    reason = models.CharField(max_length=500)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(target="WEBSITE_PREVIEW"), name="ps_target_bound")
        ]


class ScheduleOutcome(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.OneToOneField(
        PublicationSchedule, on_delete=models.PROTECT, related_name="outcome"
    )
    action = models.CharField(max_length=16)
    reason = models.CharField(max_length=128)
    actor_kind = models.CharField(max_length=16)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    publication_action = models.OneToOneField(
        "experimental_publication.PublicationAction", null=True, on_delete=models.PROTECT
    )
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=["PUBLISHED", "CANCELLED", "HOLD"]), name="ps_outcome_kind"
            )
        ]
