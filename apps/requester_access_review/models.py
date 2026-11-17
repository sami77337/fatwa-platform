import uuid

from django.db import models
from django.db.models import Q


class AccessReview(models.Model):
    """A request from an existing capability; never a replacement credential."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    grant = models.OneToOneField("delivery_queue.RequesterTrackingToken", on_delete=models.PROTECT)
    reason = models.CharField(max_length=24)
    state = models.CharField(max_length=16, default="REQUESTED")
    revision = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True)
    acknowledged_by = models.CharField(max_length=128, blank=True)
    closed_at = models.DateTimeField(null=True)
    closed_by = models.CharField(max_length=128, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(reason__in=("LOST_COPY", "EXPOSED")), name="rar_reason"),
            models.CheckConstraint(condition=(
                Q(state="REQUESTED", revision=1, acknowledged_at__isnull=True, acknowledged_by="",
                  closed_at__isnull=True, closed_by="")
                | (Q(state="VERIFYING", revision=2, acknowledged_at__isnull=False,
                     closed_at__isnull=True, closed_by="") & ~Q(acknowledged_by=""))
                | (Q(state="CLOSED", revision=3, acknowledged_at__isnull=False,
                     closed_at__isnull=False) & ~Q(acknowledged_by="") & ~Q(closed_by=""))
            ), name="rar_state_revision"),
        ]
