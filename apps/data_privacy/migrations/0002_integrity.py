"""Immutable dated classification chain; no changes to source or permission rows."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION dp_classification_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous data_privacy_classificationrevision%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'classification history immutable' USING ERRCODE='23514';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.target_kind||':'||NEW.target_id::text,391395));
 SELECT * INTO previous FROM data_privacy_classificationrevision
  WHERE target_kind=NEW.target_kind AND target_id=NEW.target_id ORDER BY number DESC LIMIT 1;
 IF NEW.number<>coalesce(previous.number,0)+1
  OR NEW.previous_digest<>coalesce(previous.digest,repeat('0',64))
  OR NEW.canonical_payload::jsonb IS DISTINCT FROM
    to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.source_digest !~ '^[a-f0-9]{64}$'
  OR NEW.request_digest !~ '^[a-f0-9]{64}$'
  OR NEW.policy_digest !~ '^[a-f0-9]{64}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR btrim(NEW.note)='' OR length(NEW.note)>1000 THEN
  RAISE EXCEPTION 'classification revision or seal invalid' USING ERRCODE='23514';
 END IF;
 NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER dp_classification_guard BEFORE INSERT OR UPDATE OR DELETE
 ON data_privacy_classificationrevision FOR EACH ROW EXECUTE FUNCTION dp_classification_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("data_privacy", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER IF EXISTS dp_classification_guard ON data_privacy_classificationrevision;"
            " DROP FUNCTION IF EXISTS dp_classification_guard();",
        )
    ]
