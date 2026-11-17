"""Single-use verified-recovery receipts; no credentials or production grants."""

import django.db.models.deletion
from django.db import migrations, models


_SQL = """
CREATE FUNCTION rar_consumed_recovery_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'consumed recovery assertion immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER rar_consumed_recovery_guard
    BEFORE UPDATE OR DELETE ON requester_access_review_usedrecoveryassertion
    FOR EACH ROW EXECUTE FUNCTION rar_consumed_recovery_immutable();
"""
_REVERSE = """
DROP TRIGGER rar_consumed_recovery_guard ON requester_access_review_usedrecoveryassertion;
DROP FUNCTION rar_consumed_recovery_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("requester_access_review", "0001_initial"),
        ("casework", "0004_case_delivery_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="UsedRecoveryAssertion",
            fields=[
                ("digest", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("issuer_id", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="casework.case",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="usedrecoveryassertion",
            constraint=models.CheckConstraint(
                condition=models.Q(digest__regex=r"^[a-f0-9]{64}$"),
                name="rar_recovery_digest",
            ),
        ),
        migrations.RunSQL(_SQL, _REVERSE),
    ]
