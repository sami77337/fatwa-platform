import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("casework", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="SeenUpdate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("provider_id", models.CharField(max_length=128)),
                ("subject_id", models.CharField(max_length=128)),
                ("auth_epoch", models.CharField(max_length=64)),
                ("seen_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                            to="casework.caseevent")),
            ],
            options={"constraints": [models.UniqueConstraint(
                fields=("provider_id", "subject_id", "event"), name="team_seen_identity_event",
            )]},
        ),
        migrations.RunSQL(
            sql="""
            CREATE FUNCTION team_seen_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'team_seen_update_immutable'; END;
            $$;
            CREATE TRIGGER team_seen_immutable BEFORE UPDATE OR DELETE ON team_updates_seenupdate
            FOR EACH ROW EXECUTE FUNCTION team_seen_immutable();
            """,
            reverse_sql="""
            DROP TRIGGER team_seen_immutable ON team_updates_seenupdate;
            DROP FUNCTION team_seen_immutable();
            """,
        ),
    ]
