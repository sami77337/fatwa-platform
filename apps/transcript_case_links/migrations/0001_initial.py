import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("casework", "0004_case_delivery_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="TranscriptUpload",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("bundle", models.BinaryField()),
                ("sha256", models.CharField(max_length=64)),
                ("subject_id", models.CharField(max_length=128)),
                ("provider_id", models.CharField(max_length=128)),
                ("auth_epoch", models.CharField(max_length=64)),
                ("case_revision", models.PositiveIntegerField()),
                ("evidence_version", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="casework.case"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TranscriptLink",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("external_id", models.CharField(max_length=100)),
                ("question_sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="casework.case"
                    ),
                ),
                (
                    "event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT, to="casework.caseevent"
                    ),
                ),
                (
                    "evidence",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT, to="casework.caseevidence"
                    ),
                ),
                (
                    "upload",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="transcript_case_links.transcriptupload",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("case", "external_id"), name="transcript_case_source_once"
                    )
                ],
            },
        ),
    ]
