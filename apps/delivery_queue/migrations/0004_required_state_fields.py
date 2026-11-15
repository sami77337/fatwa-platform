"""Reject SQL NULL bypasses in state-dependent required fields."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("delivery_queue", "0003_signed_context_and_attempt")]
    operations = [
        migrations.AddConstraint(
            model_name="deliveryintent",
            constraint=models.CheckConstraint(condition=(
                models.Q(state="STAGED")
                | models.Q(state__in=["LEASED", "UNKNOWN_REQUIRES_RECONCILIATION"],
                           lease_token_sha256__isnull=False)
                | models.Q(state__in=["SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW"],
                           provider_status__isnull=False)
            ), name="dq_intent_required_state_fields"),
        ),
    ]
