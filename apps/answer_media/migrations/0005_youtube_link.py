"""A typed external URL is immutable metadata, never downloaded video bytes."""

from importlib import import_module

from django.db import migrations, models

_previous = import_module("apps.answer_media.migrations.0003_media_metadata_guards").SQL
REVERSE = _previous.split("CREATE TRIGGER", 1)[0].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)
_link = r"""
 IF NEW.kind='YOUTUBE_LINK' THEN
  d:=NEW.metadata;
  IF NEW.ordinal=1 OR NEW.media_type<>'text/uri-list'
   OR NEW.storage_backend<>'inline-database-v1' OR NEW.original IS NULL
   OR NEW.size NOT BETWEEN 1 AND 1024
   OR jsonb_typeof(d) IS DISTINCT FROM 'object'
   OR NOT (d ?& ARRAY['external','provider','video_id','url','label','availability'])
   OR d-ARRAY['external','provider','video_id','url','label','availability']<>'{}'::jsonb
   OR d->'external' IS DISTINCT FROM 'true'::jsonb
   OR jsonb_typeof(d->'provider') IS DISTINCT FROM 'string'
   OR jsonb_typeof(d->'video_id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(d->'url') IS DISTINCT FROM 'string'
   OR jsonb_typeof(d->'availability') IS DISTINCT FROM 'string'
   OR d->>'provider' IS DISTINCT FROM 'YOUTUBE'
   OR d->>'availability' IS DISTINCT FROM 'UNVERIFIED'
   OR (d->>'video_id' ~ '^[A-Za-z0-9_-]{11}$') IS NOT TRUE
   OR d->>'url' IS DISTINCT FROM 'https://www.youtube.com/watch?v='||(d->>'video_id')
   OR NEW.filename IS DISTINCT FROM 'youtube-'||(d->>'video_id')||'.url'
   OR jsonb_typeof(d->'label') IS DISTINCT FROM 'string'
   OR length(d->>'label') NOT BETWEEN 1 AND 200 OR btrim(d->>'label')=''
   OR d->>'label' ~ '[[:cntrl:]]'
   OR convert_from(NEW.original,'UTF8') NOT IN (
      'https://www.youtube.com/watch?v='||(d->>'video_id'),
      'https://youtube.com/watch?v='||(d->>'video_id'),
      'https://youtu.be/'||(d->>'video_id'))
  THEN RAISE EXCEPTION 'invalid external YouTube reference' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
"""
SQL = REVERSE.replace("BEGIN\n", "BEGIN\n" + _link, 1)


class Migration(migrations.Migration):
    dependencies = [
        ("answer_media", "0004_answerpart_storage_backend_answerpart_storage_key_and_more")
    ]
    operations = [
        migrations.RemoveConstraint(model_name="answerpart", name="am_kind"),
        migrations.AddConstraint(
            model_name="answerpart",
            constraint=models.CheckConstraint(
                condition=models.Q(kind__in=("TEXT", "FILE", "AUDIO", "IMAGE", "YOUTUBE_LINK")),
                name="am_kind",
            ),
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
