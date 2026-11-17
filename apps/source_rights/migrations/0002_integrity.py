"""Append-only rights history, source/case bindings and independent current review."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION source_rights_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'source identity immutable' USING ERRCODE='23514'; END IF;
 IF NEW.sha256 !~ '^[a-f0-9]{64}$' OR jsonb_typeof(NEW.snapshot)<>'object'
 OR NEW.snapshot->>'kind' IS DISTINCT FROM NEW.kind THEN
  RAISE EXCEPTION 'source identity invalid' USING ERRCODE='23514'; END IF;
 IF NEW.heading_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM reference_referenceheading h WHERE h.id=NEW.heading_id
   AND h.edition_id::text=NEW.snapshot->'source'->>'edition_id'
   AND h.source_row_id::text=NEW.snapshot->'source'->>'source_row_id'
 ) THEN RAISE EXCEPTION 'source heading mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.transcript_id IS NOT NULL AND NEW.snapshot->>'link_id' IS DISTINCT FROM NEW.transcript_id::text THEN
  RAISE EXCEPTION 'source transcript mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_rights_source_guard BEFORE INSERT OR UPDATE OR DELETE ON source_rights_sourceversion
 FOR EACH ROW EXECUTE FUNCTION source_rights_source_guard();

CREATE FUNCTION source_rights_registration_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'source registration immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.case_id::text,311));
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR (SELECT count(*) FROM source_rights_sourceregistration WHERE case_id=NEW.case_id)>=64
 OR EXISTS (SELECT 1 FROM source_rights_sourceversion s JOIN transcript_case_links_transcriptlink t ON t.id=s.transcript_id
             WHERE s.id=NEW.source_id AND t.case_id<>NEW.case_id) THEN
  RAISE EXCEPTION 'source registration scope invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_rights_registration_guard BEFORE INSERT OR UPDATE OR DELETE ON source_rights_sourceregistration
 FOR EACH ROW EXECUTE FUNCTION source_rights_registration_guard();

CREATE FUNCTION source_rights_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE k text;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'rights revisions immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.case_id::text,311));
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 SELECT kind INTO k FROM source_rights_sourceversion WHERE id=NEW.source_id;
 IF NEW.number<>(SELECT count(*)+1 FROM source_rights_rightsrevision WHERE case_id=NEW.case_id AND source_id=NEW.source_id)
 OR NOT EXISTS(SELECT 1 FROM source_rights_sourceregistration WHERE case_id=NEW.case_id AND source_id=NEW.source_id)
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.basis !~ '\S' OR NEW.note !~ '\S'
 OR NEW.valid_until<=statement_timestamp() OR NEW.valid_until>statement_timestamp()+interval '24 hours 1 minute'
 OR jsonb_typeof(NEW.uses)<>'array' THEN
  RAISE EXCEPTION 'rights revision invalid' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(NEW.uses)>4
 OR (SELECT count(*) FROM jsonb_array_elements_text(NEW.uses))<>(SELECT count(DISTINCT v) FROM jsonb_array_elements_text(NEW.uses) v)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.uses) v WHERE v NOT IN ('READ','CITE','RELATE','PREVIEW_METADATA'))
 OR (k='PRIVATE_TRANSCRIPT' AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.uses) v WHERE v NOT IN ('READ','RELATE'))) THEN
  RAISE EXCEPTION 'rights use invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_rights_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON source_rights_rightsrevision
 FOR EACH ROW EXECUTE FUNCTION source_rights_revision_guard();

CREATE FUNCTION source_rights_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r source_rights_rightsrevision%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'rights actions immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM source_rights_rightsrevision WHERE id=NEW.revision_id;
 PERFORM pg_advisory_xact_lock(hashtextextended(r.case_id::text,311));
 PERFORM 1 FROM casework_case WHERE id=r.case_id FOR UPDATE;
 IF r.number<>(SELECT max(number) FROM source_rights_rightsrevision WHERE case_id=r.case_id AND source_id=r.source_id)
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.note !~ '\S'
 OR EXISTS(SELECT 1 FROM source_rights_rightsaction WHERE revision_id=r.id AND action IN ('REJECT','REVOKE'))
 OR (NEW.action IN ('APPROVE','REJECT') AND (r.valid_until<=statement_timestamp()
      OR EXISTS(SELECT 1 FROM source_rights_rightsaction WHERE revision_id=r.id)))
 OR (NEW.action='APPROVE' AND NEW.subject_id=r.subject_id AND NEW.provider_id=r.provider_id) THEN
  RAISE EXCEPTION 'current independent rights review required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_rights_action_guard BEFORE INSERT OR UPDATE OR DELETE ON source_rights_rightsaction
 FOR EACH ROW EXECUTE FUNCTION source_rights_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("source_rights", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER source_rights_action_guard ON source_rights_rightsaction;
        DROP FUNCTION source_rights_action_guard();
        DROP TRIGGER source_rights_revision_guard ON source_rights_rightsrevision;
        DROP FUNCTION source_rights_revision_guard();
        DROP TRIGGER source_rights_registration_guard ON source_rights_sourceregistration;
        DROP FUNCTION source_rights_registration_guard();
        DROP TRIGGER source_rights_source_guard ON source_rights_sourceversion;
        DROP FUNCTION source_rights_source_guard();
    """,
        )
    ]
