"""Append-only assignment metadata; never a case access grant or evidence change."""

from django.db import models
from django.db.models import Q

MUFTI_ACTIONS = (
    "CLAIM",
    "RELEASE",
    "TRANSFER",
    "ADD_CONTRIBUTOR",
    "ADD_REVIEWER",
    "REMOVE_PARTICIPANT",
)
ADMIN_ACTIONS = ("SET_PRIMARY", "CLEAR_PRIMARY")
ACTIONS = (*MUFTI_ACTIONS, *ADMIN_ACTIONS)


class AssignmentEvent(models.Model):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT, related_name="assignments")
    sequence = models.PositiveIntegerField()
    action = models.CharField(max_length=24)
    target_subject = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    actor_role = models.CharField(max_length=24, default="", blank=True)
    reason = models.TextField(default="", blank=True)
    command_id = models.UUIDField(null=True, blank=True)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    previous_sha256 = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    transaction_id = models.BigIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["case", "sequence"], name="ca_event_sequence"),
            models.UniqueConstraint(fields=["case", "command_id"], name="ca_event_command"),
            models.CheckConstraint(condition=Q(action__in=ACTIONS), name="ca_event_action"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, case_revision__gte=1, evidence_version__gte=1),
                name="ca_event_versions",
            ),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$")
                & Q(previous_sha256__regex=r"^[a-f0-9]{64}$"),
                name="ca_event_digests",
            ),
        ]


class PriorityEvent(models.Model):
    """Explicit human priority, separate from derived queue status or case authority."""

    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT, related_name="priorities")
    sequence = models.PositiveIntegerField()
    value = models.CharField(max_length=64)
    label = models.CharField(max_length=128)
    rank = models.PositiveSmallIntegerField()
    policy_sha256 = models.CharField(max_length=64)
    reason = models.TextField()
    command_id = models.UUIDField()
    subject_id = models.CharField(max_length=128)
    actor_role = models.CharField(max_length=24)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    previous_sha256 = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    transaction_id = models.BigIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["case", "sequence"], name="ca_priority_sequence"),
            models.UniqueConstraint(fields=["case", "command_id"], name="ca_priority_command"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, case_revision__gte=1, evidence_version__gte=1)
                & Q(rank__lte=100),
                name="ca_priority_versions",
            ),
            models.CheckConstraint(
                condition=Q(actor_role__in=("MUFTI", "ORGANIZER", "ORGANIZER_ADMIN")),
                name="ca_priority_actor_role",
            ),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$")
                & Q(previous_sha256__regex=r"^[a-f0-9]{64}$")
                & Q(policy_sha256__regex=r"^[a-f0-9]{64}$"),
                name="ca_priority_digests",
            ),
        ]
