"""Isolated synthetic multi-case status tickets and append-only history."""
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


def require_empty_tracking_data(apps, schema_editor):
    # New app tables have not been created yet; nothing is migrated from user files.
    # Existing delivery receipts remain untouched.
    return None


class Migration(migrations.Migration):
    dependencies = [("delivery_queue", "0005_provider_signature_evidence")]
    operations = [
        migrations.RunPython(require_empty_tracking_data, migrations.RunPython.noop),
        migrations.CreateModel(
            name="RequesterTrackingCase",
            fields=[
                ("case_key", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("stage", models.CharField(max_length=40, default="RECEIVED", choices=[
                    (value, value) for value in (
                        "RECEIVED", "UNDER_REVIEW", "NEEDS_CLARIFICATION",
                        "WITH_MUFTI", "RETURNED_FOR_CHANGES",
                    )
                ])),
                ("revision", models.PositiveIntegerField(default=1)),
                ("registered_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fatwa_requester_tracking_case",
                "constraints": [
                    models.CheckConstraint(condition=Q(revision__gte=1), name="dq_track_revision_positive"),
                    models.CheckConstraint(
                        condition=Q(stage__in=[
                            "RECEIVED", "UNDER_REVIEW", "NEEDS_CLARIFICATION",
                            "WITH_MUFTI", "RETURNED_FOR_CHANGES",
                        ]),
                        name="dq_track_stage_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RequesterTrackingToken",
            fields=[
                ("token_sha256", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(null=True, blank=True)),
                ("case", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="tokens", to="delivery_queue.requestertrackingcase",
                )),
            ],
            options={
                "db_table": "fatwa_requester_tracking_token",
                "constraints": [
                    models.UniqueConstraint(
                        fields=["case"], condition=Q(revoked_at__isnull=True),
                        name="dq_tracking_one_active_token",
                    ),
                    models.CheckConstraint(
                        condition=Q(token_sha256__regex=r"^[a-f0-9]{64}$"),
                        name="dq_tracking_token_hash_format",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RequesterTrackingEvent",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
                )),
                ("sequence", models.PositiveIntegerField()),
                ("old_stage", models.CharField(max_length=40)),
                ("new_stage", models.CharField(max_length=40)),
                ("actor_id", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("case", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="events", to="delivery_queue.requestertrackingcase",
                )),
            ],
            options={
                "db_table": "fatwa_requester_tracking_event",
                "constraints": [
                    models.UniqueConstraint(
                        fields=["case", "sequence"],
                        name="dq_tracking_event_sequence_unique",
                    ),
                ],
            },
        ),
        migrations.RunSQL(
            sql=(
                "CREATE TRIGGER fatwa_requester_tracking_event_immutable "
                "BEFORE UPDATE OR DELETE ON public.fatwa_requester_tracking_event "
                "FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows()"
            ),
            reverse_sql=(
                "DROP TRIGGER IF EXISTS fatwa_requester_tracking_event_immutable "
                "ON public.fatwa_requester_tracking_event"
            ),
        ),
    ]
