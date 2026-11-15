"""Add a sequenced SHA-256 chain and locked head to the synthetic delivery audit."""
from django.db import migrations, models
import django.utils.timezone


def seed_head(apps, schema_editor):
    Head = apps.get_model("delivery_queue", "DeliveryAuditHead")
    Head.objects.using(schema_editor.connection.alias).get_or_create(
        id=1, defaults={"sequence": 0, "digest": ""}
    )


class Migration(migrations.Migration):
    dependencies = [("delivery_queue", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="DeliveryAuditHead",
            fields=[
                ("id", models.PositiveSmallIntegerField(primary_key=True, serialize=False)),
                ("sequence", models.PositiveBigIntegerField(default=0)),
                ("digest", models.CharField(default="", max_length=64)),
            ],
            options={"db_table": "fatwa_delivery_audit_head"},
        ),
        migrations.AddField(
            model_name="deliveryauditevent",
            name="sequence",
            field=models.PositiveBigIntegerField(default=0, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="deliveryauditevent",
            name="previous_digest",
            field=models.CharField(default="", max_length=64),
        ),
        migrations.AddField(
            model_name="deliveryauditevent",
            name="digest",
            field=models.CharField(default="", max_length=64),
        ),
        migrations.AlterField(
            model_name="deliveryauditevent",
            name="recorded_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.RunPython(seed_head, migrations.RunPython.noop),
    ]
