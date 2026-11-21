"""Bind the added adapter to immutable reviewed-recording source coordinates."""

from importlib import import_module

from django.db import migrations

_previous = import_module("apps.canonical_search.migrations.0002_integrity").SQL
_start = _previous.index("CREATE FUNCTION cs_document_insert()")
_end = _previous.index("CREATE FUNCTION cs_generation_complete()")
REVERSE = _previous[_start:_end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
_fallback = " ELSE\n   RAISE EXCEPTION 'search source adapter unavailable'"
_recording = r"""
 ELSIF NEW.kind='RECORDING_TRANSCRIPT' THEN
   IF NOT (NEW.pin ?& ARRAY['transcript_id','transcript_digest','part_id','part_sha256',
     'segment_index','segment_sha256','start_ms','end_ms'])
   OR jsonb_typeof(NEW.pin->'segment_index') IS DISTINCT FROM 'number'
   OR (NEW.pin->>'segment_index' ~ '^[0-5]$') IS NOT TRUE
   THEN RAISE EXCEPTION 'search recording coordinates missing' USING ERRCODE='23514'; END IF;
   SELECT r.*, p.sha256 AS part_sha256 INTO recording
   FROM public_answer_media_recordingtranscript r
   JOIN answer_media_answerpart p ON p.id=r.part_id
   WHERE r.id=NEW.source_id AND r.case_id=g.case_id;
   segment:=recording.segments->((NEW.pin->>'segment_index')::integer);
   IF recording.id IS NULL OR segment IS NULL
   OR NEW.pin->>'transcript_id' IS DISTINCT FROM recording.id::text
   OR NEW.pin->>'transcript_digest' IS DISTINCT FROM recording.digest
   OR NEW.pin->>'part_id' IS DISTINCT FROM recording.part_id::text
   OR NEW.pin->>'part_sha256' IS DISTINCT FROM recording.part_sha256
   OR NEW.pin->'version' IS DISTINCT FROM to_jsonb(recording.number)
   OR NEW.pin->>'segment_sha256' IS DISTINCT FROM segment->>'sha256'
   OR NEW.pin->'start_ms' IS DISTINCT FROM segment->'start_ms'
   OR NEW.pin->'end_ms' IS DISTINCT FROM segment->'end_ms'
   THEN RAISE EXCEPTION 'search recording coordinates differ from source' USING ERRCODE='23514'; END IF;
   source_text:=substr(recording.text, (segment->>'char_start')::integer+1,
     (segment->>'char_end')::integer-(segment->>'char_start')::integer);
   source_hash:=recording.digest;
 ELSE
   RAISE EXCEPTION 'search source adapter unavailable'"""
assert REVERSE.count(_fallback) == 1
SQL = REVERSE.replace(
    "source_hash text;", "source_hash text; recording record; segment jsonb;", 1
).replace(_fallback, _recording, 1)


class Migration(migrations.Migration):
    dependencies = [
        ("canonical_search", "0003_unique_sources"),
        ("public_answer_media", "0002_integrity"),
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
