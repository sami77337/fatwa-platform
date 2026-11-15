"""Fresh synthetic queue only: immutable provider-signed receipt evidence."""
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


def require_empty_provider_receipts(apps, schema_editor):
    Receipt = apps.get_model("delivery_queue", "ProviderReceipt")
    if Receipt.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError(
            "Existing provider receipt history requires a separately approved migration"
        )


class Migration(migrations.Migration):
    dependencies = [("delivery_queue", "0003_signed_context_and_attempt")]
    operations = [
        migrations.RunPython(require_empty_provider_receipts, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ProviderSignatureEvidence",
            fields=[
                (
                    "receipt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        related_name="signature_evidence",
                        serialize=False,
                        to="delivery_queue.providerreceipt",
                    ),
                ),
                ("envelope", models.JSONField()),
                ("envelope_sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "fatwa_delivery_provider_signature_evidence",
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(envelope_sha256__regex=r"^[a-f0-9]{64}$"),
                        name="dq_provider_sig_sha_format",
                    ),
                ],
            },
        ),
        migrations.RunSQL(
            sql=(
                "CREATE TRIGGER fatwa_provider_signature_immutable "
                "BEFORE UPDATE OR DELETE ON public.fatwa_delivery_provider_signature_evidence "
                "FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows()"
            ),
            reverse_sql=(
                "DROP TRIGGER IF EXISTS fatwa_provider_signature_immutable "
                "ON public.fatwa_delivery_provider_signature_evidence"
            ),
        ),
    ]
