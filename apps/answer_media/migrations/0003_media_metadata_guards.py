from django.db import migrations

SQL = r"""
CREATE FUNCTION answer_media_metadata_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d jsonb; expected_kind text; expected_extension text; number_value numeric;
BEGIN
 IF NEW.ordinal=1 THEN
  IF NEW.metadata <> '{}'::jsonb THEN
   RAISE EXCEPTION 'answer text metadata invalid' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 d := NEW.metadata;
 CASE NEW.media_type
  WHEN 'text/plain' THEN expected_kind:='FILE'; expected_extension:='\.txt$';
  WHEN 'application/pdf' THEN expected_kind:='FILE'; expected_extension:='\.pdf$';
  WHEN 'image/jpeg' THEN expected_kind:='IMAGE'; expected_extension:='\.jpe?g$';
  WHEN 'image/png' THEN expected_kind:='IMAGE'; expected_extension:='\.png$';
  WHEN 'image/webp' THEN expected_kind:='IMAGE'; expected_extension:='\.webp$';
  WHEN 'audio/mpeg' THEN expected_kind:='AUDIO'; expected_extension:='\.mp3$';
  WHEN 'audio/mp4' THEN expected_kind:='AUDIO'; expected_extension:='\.m4a$';
  WHEN 'audio/wav' THEN expected_kind:='AUDIO'; expected_extension:='\.wav$';
  ELSE RAISE EXCEPTION 'answer media type invalid' USING ERRCODE='23514';
 END CASE;
 IF NEW.kind<>expected_kind
  OR NEW.filename !~ '^[A-Za-z0-9][A-Za-z0-9_. -]{0,94}\.[A-Za-z0-9]{2,4}$'
  OR lower(NEW.filename) !~ expected_extension
  OR jsonb_typeof(d)<>'object' OR (d->'validated') IS DISTINCT FROM 'true'::jsonb
 THEN RAISE EXCEPTION 'answer media metadata invalid' USING ERRCODE='23514'; END IF;
 IF NEW.media_type='text/plain' THEN
  IF NEW.size>65536 OR d<>'{"validated":true,"encoding":"UTF-8"}'::jsonb THEN
   RAISE EXCEPTION 'answer text file metadata invalid' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.media_type='application/pdf' THEN
  IF d-ARRAY['validated','pages','active_content']<>'{}'::jsonb
   OR (d->'active_content') IS DISTINCT FROM 'false'::jsonb
   OR jsonb_typeof(d->'pages') IS DISTINCT FROM 'number' THEN
   RAISE EXCEPTION 'answer pdf metadata invalid' USING ERRCODE='23514';
  END IF;
  number_value := (d->>'pages')::numeric;
  IF number_value<1 OR number_value>10 OR number_value<>trunc(number_value) THEN
   RAISE EXCEPTION 'answer pdf limit invalid' USING ERRCODE='23514';
  END IF;
 ELSIF expected_kind='IMAGE' THEN
  IF d-ARRAY['validated','width','height','format']<>'{}'::jsonb
   OR jsonb_typeof(d->'width') IS DISTINCT FROM 'number'
   OR jsonb_typeof(d->'height') IS DISTINCT FROM 'number'
   OR (d->>'format') IS DISTINCT FROM (CASE NEW.media_type WHEN 'image/jpeg' THEN 'JPEG'
      WHEN 'image/png' THEN 'PNG' ELSE 'WEBP' END) THEN
   RAISE EXCEPTION 'answer image metadata invalid' USING ERRCODE='23514';
  END IF;
  IF (d->>'width')::numeric<1 OR (d->>'height')::numeric<1
   OR (d->>'width')::numeric<>trunc((d->>'width')::numeric)
   OR (d->>'height')::numeric<>trunc((d->>'height')::numeric)
   OR (d->>'width')::numeric*(d->>'height')::numeric>4000000 THEN
   RAISE EXCEPTION 'answer image limit invalid' USING ERRCODE='23514';
  END IF;
 ELSE
  IF d-ARRAY['validated','channels','sample_rate','duration_seconds']<>'{}'::jsonb
   OR jsonb_typeof(d->'channels') IS DISTINCT FROM 'number'
   OR jsonb_typeof(d->'sample_rate') IS DISTINCT FROM 'number'
   OR jsonb_typeof(d->'duration_seconds') IS DISTINCT FROM 'number' THEN
   RAISE EXCEPTION 'answer audio metadata invalid' USING ERRCODE='23514';
  END IF;
  IF (d->>'channels')::numeric NOT IN (1,2)
   OR (d->>'sample_rate')::numeric<8000 OR (d->>'sample_rate')::numeric>96000
   OR (d->>'sample_rate')::numeric<>trunc((d->>'sample_rate')::numeric)
   OR (d->>'duration_seconds')::numeric<=0 OR (d->>'duration_seconds')::numeric>120 THEN
   RAISE EXCEPTION 'answer audio limit invalid' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER answer_media_metadata_guard BEFORE INSERT ON answer_media_answerpart
 FOR EACH ROW EXECUTE FUNCTION answer_media_metadata_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("answer_media", "0002_immutable_guards")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER answer_media_metadata_guard ON answer_media_answerpart;
        DROP FUNCTION answer_media_metadata_guard();
    """,
        )
    ]
