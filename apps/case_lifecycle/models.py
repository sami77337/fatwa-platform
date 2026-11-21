import uuid

from django.db import models
from django.db.models import Q

STATES = ("OPEN", "CLOSED", "ARCHIVED")
ACTIONS = ("CLOSE", "REOPEN", "ARCHIVE", "RESTORE", "FOLLOWUP")


class LifecycleEvent(models.Model):
    """Immutable orthogonal lifecycle; never a replacement for Case.stage."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    before_state = models.CharField(max_length=16)
    state = models.CharField(max_length=16)
    reason = models.TextField()
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    answer = models.ForeignKey("casework.AnswerRevision", null=True, on_delete=models.PROTECT)
    actor_kind = models.CharField(max_length=24)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    policy_epoch = models.CharField(max_length=128)
    command_id = models.UUIDField()
    command_sha256 = models.CharField(max_length=64)
    canonical_event = models.OneToOneField(
        "casework.CaseEvent", null=True, on_delete=models.PROTECT
    )
    context = models.JSONField(default=dict)
    previous_sha256 = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("version",)
        constraints = [
            models.UniqueConstraint(fields=("case", "version"), name="lc_case_version"),
            models.UniqueConstraint(
                fields=("case", "provider_id", "subject_id", "command_id"),
                name="lc_actor_command",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1, version__lte=4096), name="lc_version_bound"
            ),
            models.CheckConstraint(condition=Q(action__in=ACTIONS), name="lc_action"),
            models.CheckConstraint(
                condition=Q(before_state__in=STATES, state__in=STATES), name="lc_states"
            ),
            models.CheckConstraint(
                condition=(
                    Q(actor_kind="STAFF", canonical_event__isnull=True)
                    | Q(
                        actor_kind="REQUESTER_EVENT",
                        action="FOLLOWUP",
                        canonical_event__isnull=False,
                    )
                ),
                name="lc_actor_kind",
            ),
            models.CheckConstraint(
                condition=Q(case_revision__gte=1, evidence_version__gte=1), name="lc_case_pins"
            ),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[a-f0-9]{64}$")
                & Q(previous_sha256__regex=r"^[a-f0-9]{64}$")
                & Q(command_sha256__regex=r"^[a-f0-9]{64}$"),
                name="lc_digests",
            ),
        ]
