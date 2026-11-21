"""Accept bounded original videos while retaining every original/evidence guard."""

from importlib import import_module

from django.db import migrations, models

OLD = import_module(
    "apps.case_attachments.migrations.0004_caseattachment_storage_backend_and_more"
).NEW
NEW = (
    OLD.replace("'audio/wav')", "'audio/wav','video/webm','video/mp4')")
    .replace("|m4a|wav)$", "|m4a|wav|webm|mp4)$")
    .replace(
        "WHEN NEW.media_type LIKE 'image/%' THEN 'image' ELSE 'audio' END)",
        "WHEN NEW.media_type LIKE 'image/%' THEN 'image' "
        "WHEN NEW.media_type LIKE 'video/%' THEN 'video' ELSE 'audio' END)",
    )
)
NEW = NEW.replace(
    " IF NOT EXISTS (",
    """ IF NEW.kind='video' AND (
    NEW.validation_metadata->>'kind' IS DISTINCT FROM 'video'
    OR (NEW.media_type='video/webm' AND NEW.filename !~* '\\.webm$')
    OR (NEW.media_type='video/mp4' AND NEW.filename !~* '\\.mp4$')
    OR jsonb_typeof(NEW.validation_metadata->'width') IS DISTINCT FROM 'number'
    OR jsonb_typeof(NEW.validation_metadata->'height') IS DISTINCT FROM 'number'
    OR jsonb_typeof(NEW.validation_metadata->'duration_seconds') IS DISTINCT FROM 'number'
    OR (NEW.validation_metadata->>'width')::numeric NOT BETWEEN 1 AND 1280
    OR (NEW.validation_metadata->>'height')::numeric NOT BETWEEN 1 AND 720
    OR (NEW.validation_metadata->>'duration_seconds')::numeric <= 0
    OR (NEW.validation_metadata->>'duration_seconds')::numeric > 60
    OR coalesce(NEW.validation_metadata->>'codec','') NOT IN ('h264','vp8','vp9')
 ) THEN
  RAISE EXCEPTION 'attachment video metadata invalid' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (""",
)
REVERSE = """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM case_attachments_caseattachment WHERE kind='video') THEN
  RAISE EXCEPTION 'video originals prevent attachment schema downgrade';
 END IF;
END $$;
""" + OLD


class Migration(migrations.Migration):
    dependencies = [
        ("case_attachments", "0004_caseattachment_storage_backend_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="caseattachment", name="ca_type"),
        migrations.AddConstraint(
            model_name="caseattachment",
            constraint=models.CheckConstraint(
                condition=models.Q(media_type__in=(
                    "text/plain", "application/pdf", "image/jpeg", "image/png",
                    "image/webp", "audio/mpeg", "audio/mp4", "audio/wav",
                    "video/webm", "video/mp4",
                )),
                name="ca_type",
            ),
        ),
        migrations.RunSQL(NEW, REVERSE),
    ]
