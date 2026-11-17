from django.db import models


class SeenUpdate(models.Model):
    """An explicit inbox acknowledgement, never a case/evidence review receipt."""

    event = models.ForeignKey("casework.CaseEvent", on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "event"], name="team_seen_identity_event",
            ),
        ]
