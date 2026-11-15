"""Add immutable signed metadata and hashed attempt identity in fresh synthetic DBs."""
from django.db import migrations, models
import django.db.models.deletion


def require_empty_queue(apps, schema_editor):
    Intent = apps.get_model("delivery_queue", "DeliveryIntent")
    if Intent.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError("Existing delivery data requires a separately approved migration; no automatic conversion")


def install_immutable_triggers(apps, schema_editor):
    for table in ("fatwa_delivery_signed_context", "fatwa_delivery_attempt"):
        schema_editor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows()")


def remove_immutable_triggers(apps, schema_editor):
    for table in ("fatwa_delivery_signed_context", "fatwa_delivery_attempt"):
        schema_editor.execute(f"DROP TRIGGER {table}_immutable ON public.{table}")


class Migration(migrations.Migration):
    dependencies = [("delivery_queue", "0002_delivery_audit_hash_chain")]
    operations = [
        migrations.RunPython(require_empty_queue, migrations.RunPython.noop),
        migrations.CreateModel(name="SignedDeliveryContext", fields=[
            ("approval", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, related_name="signed_context", serialize=False, to="delivery_queue.approvalclaim")),
            ("envelope", models.JSONField()),
            ("envelope_sha256", models.CharField(max_length=64)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={"db_table": "fatwa_delivery_signed_context"}),
        migrations.CreateModel(name="DeliveryAttempt", fields=[
            ("intent", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, related_name="attempt", serialize=False, to="delivery_queue.deliveryintent")),
            ("worker_id", models.CharField(max_length=128)),
            ("token_sha256", models.CharField(max_length=64)),
            ("expires_at", models.DateTimeField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={"db_table": "fatwa_delivery_attempt"}),
        migrations.RunPython(install_immutable_triggers, remove_immutable_triggers),
    ]
