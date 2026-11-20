"""Immutable selected scope/results and a serialized, bounded export state machine."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION selected_export_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE; entry jsonb;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'export scope immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF c.id IS NULL OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.selection_sha256 !~ '^[a-f0-9]{64}$'
 OR NEW.expires_at<=statement_timestamp() OR NEW.expires_at>statement_timestamp()+interval '31 minutes'
 OR jsonb_typeof(NEW.selection)<>'array' OR jsonb_array_length(NEW.selection) NOT BETWEEN 1 AND 20
 OR (SELECT count(*) FROM selected_exports_exportjob WHERE case_id=NEW.case_id AND provider_id=NEW.provider_id AND subject_id=NEW.subject_id)>=32
 THEN RAISE EXCEPTION 'export scope invalid' USING ERRCODE='23514'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(NEW.selection) LOOP
  IF jsonb_typeof(entry) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(entry))<>2
  OR NOT (entry ?& ARRAY['resource','record_sha256'])
  OR jsonb_typeof(entry->'record_sha256') IS DISTINCT FROM 'string'
  OR entry->>'record_sha256' !~ '^[a-f0-9]{64}$' OR jsonb_typeof(entry->'resource') IS DISTINCT FROM 'object'
  OR (SELECT count(*) FROM jsonb_object_keys(entry->'resource'))<>9
  OR NOT (entry->'resource' ?& ARRAY['kind','identifier','sha256','edition_id','source_namespace','source_book_id','edition_key','source_archive_sha256','source_input_sha256'])
  OR EXISTS(SELECT 1 FROM jsonb_each(entry->'resource') p WHERE p.key<>'edition_id' AND jsonb_typeof(p.value) IS DISTINCT FROM 'string')
  OR entry->'resource'->>'kind' NOT IN ('REFERENCE','TRANSCRIPT','KNOWLEDGE','ATTACHMENT','ANSWER_MEDIA')
  OR entry->'resource'->>'sha256' !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'export item invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 NEW.created_at=statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER selected_export_job_guard BEFORE INSERT OR UPDATE OR DELETE ON selected_exports_exportjob
 FOR EACH ROW EXECUTE FUNCTION selected_export_job_guard();

CREATE FUNCTION selected_export_artifact_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j selected_exports_exportjob%ROWTYPE; e selected_exports_exportevent%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'export artifact immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO j FROM selected_exports_exportjob WHERE id=NEW.job_id;
 PERFORM 1 FROM casework_case WHERE id=j.case_id FOR UPDATE;
 SELECT * INTO e FROM selected_exports_exportevent WHERE job_id=j.id ORDER BY sequence DESC LIMIT 1;
 IF e.state IS DISTINCT FROM 'RUNNING' OR NEW.attempt<>e.attempt OR e.lease_until<=statement_timestamp()
 OR j.expires_at<=statement_timestamp() OR NEW.size<>octet_length(NEW.raw)
 OR NEW.sha256<>encode(sha256(NEW.raw),'hex') OR jsonb_typeof(NEW.manifest)<>'object'
 OR NEW.manifest->>'bundle_id' IS DISTINCT FROM j.id::text
 OR NEW.manifest->>'format' IS DISTINCT FROM j.format
 OR (NEW.manifest->>'requested')::integer<>jsonb_array_length(j.selection)
 THEN RAISE EXCEPTION 'export artifact binding invalid' USING ERRCODE='23514'; END IF;
 NEW.created_at=statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER selected_export_artifact_guard BEFORE INSERT OR UPDATE OR DELETE ON selected_exports_exportartifact
 FOR EACH ROW EXECUTE FUNCTION selected_export_artifact_guard();

CREATE FUNCTION selected_export_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j selected_exports_exportjob%ROWTYPE; p selected_exports_exportevent%ROWTYPE; n integer; included integer;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'export history immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO j FROM selected_exports_exportjob WHERE id=NEW.job_id;
 PERFORM 1 FROM casework_case WHERE id=j.case_id FOR UPDATE;
 SELECT * INTO p FROM selected_exports_exportevent WHERE job_id=j.id ORDER BY sequence DESC LIMIT 1;
 n=jsonb_array_length(j.selection);
 IF NEW.subject_id IS DISTINCT FROM j.subject_id OR NEW.provider_id IS DISTINCT FROM j.provider_id OR NEW.auth_epoch=''
 OR NEW.sha256 !~ '^[a-f0-9]{64}$' OR NEW.previous_sha256 !~ '^[a-f0-9]{64}$'
 OR NEW.sequence<>COALESCE(p.sequence,0)+1 OR NEW.previous_sha256<>COALESCE(p.sha256,repeat('0',64))
 OR jsonb_typeof(NEW.outcomes)<>'array' OR NEW.completed>n
 THEN RAISE EXCEPTION 'export event binding invalid' USING ERRCODE='23514'; END IF;
 IF (NEW.action='QUEUE' AND NEW.sequence>92) OR (NEW.action='START' AND NEW.sequence>93)
 OR (NEW.action IN ('READY','PARTIAL','FAIL','DOWNLOAD') AND NEW.sequence>94)
 OR (NEW.action='CANCEL' AND NEW.sequence>95)
 THEN RAISE EXCEPTION 'export terminal capacity reserved' USING ERRCODE='23514'; END IF;
 IF p.id IS NULL THEN
  IF NEW.action<>'PREPARE' OR NEW.state<>'PREPARED' OR NEW.attempt<>0 OR NEW.completed<>0
   OR NEW.lease_id IS NOT NULL OR NEW.lease_until IS NOT NULL OR NEW.artifact_sha256<>'' OR NEW.outcomes<>'[]'::jsonb
  THEN RAISE EXCEPTION 'export initial state invalid' USING ERRCODE='23514'; END IF;
 ELSIF NEW.action='EXPIRE' THEN
  IF j.expires_at>statement_timestamp() OR p.state='EXPIRED' OR NEW.state<>'EXPIRED' OR NEW.attempt<>p.attempt
  THEN RAISE EXCEPTION 'export expiry invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF j.expires_at<=statement_timestamp() OR p.state IN ('CANCELLED','EXPIRED')
  THEN RAISE EXCEPTION 'export closed' USING ERRCODE='23514'; END IF;
  IF NEW.action='QUEUE' THEN
   IF NOT (p.state IN ('PREPARED','FAILED','PARTIAL') OR (p.state='RUNNING' AND p.lease_until<=statement_timestamp()))
   OR NEW.state<>'QUEUED' OR NEW.attempt<>p.attempt OR NEW.attempt>=10 OR NEW.completed<>0
   OR NEW.outcomes<>'[]'::jsonb OR NEW.artifact_sha256<>'' OR NEW.lease_id IS NOT NULL OR NEW.lease_until IS NOT NULL
   THEN RAISE EXCEPTION 'export queue invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='START' THEN
   IF p.state<>'QUEUED' OR NEW.state<>'RUNNING' OR NEW.attempt<>p.attempt+1 OR NEW.lease_id IS NULL
   OR NEW.lease_until<=statement_timestamp() OR NEW.lease_until>statement_timestamp()+interval '3 minutes'
   OR NEW.completed<>0 OR NEW.outcomes<>'[]'::jsonb OR NEW.artifact_sha256<>''
   THEN RAISE EXCEPTION 'export claim invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action IN ('READY','PARTIAL','FAIL') THEN
   IF p.state<>'RUNNING' OR NEW.attempt<>p.attempt OR NEW.lease_id IS DISTINCT FROM p.lease_id
   OR NEW.lease_until IS DISTINCT FROM p.lease_until OR jsonb_array_length(NEW.outcomes)<>n
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.outcomes) v WHERE jsonb_typeof(v)<>'object'
      OR (SELECT count(*) FROM jsonb_object_keys(v))<>2 OR (v->>'ordinal')::integer NOT BETWEEN 1 AND n
      OR COALESCE(v->>'status','') NOT IN ('INCLUDED','UNAVAILABLE','FAILED'))
   OR (SELECT count(DISTINCT v->>'ordinal') FROM jsonb_array_elements(NEW.outcomes) v)<>n
   THEN RAISE EXCEPTION 'export completion invalid' USING ERRCODE='23514'; END IF;
   SELECT count(*) INTO included FROM jsonb_array_elements(NEW.outcomes) v WHERE v->>'status'='INCLUDED';
   IF NEW.action='FAIL' THEN
    IF NEW.state<>'FAILED' OR NEW.completed<>0 OR included<>0 OR NEW.artifact_sha256<>''
    THEN RAISE EXCEPTION 'export failure invalid' USING ERRCODE='23514'; END IF;
   ELSE
    IF NEW.state<>NEW.action OR NEW.completed<>included OR included<1 OR p.lease_until<=statement_timestamp()
    OR (NEW.state='READY' AND included<>n) OR (NEW.state='PARTIAL' AND included>=n)
    OR NOT EXISTS(SELECT 1 FROM selected_exports_exportartifact a WHERE a.job_id=j.id AND a.attempt=NEW.attempt AND a.sha256=NEW.artifact_sha256)
    THEN RAISE EXCEPTION 'export result invalid' USING ERRCODE='23514'; END IF;
   END IF;
  ELSIF NEW.action='CANCEL' THEN
   IF NEW.state<>'CANCELLED' OR NEW.attempt<>p.attempt THEN RAISE EXCEPTION 'export cancellation invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='DOWNLOAD' THEN
   IF p.state NOT IN ('READY','PARTIAL') OR NEW.state<>p.state OR NEW.attempt<>p.attempt
   THEN RAISE EXCEPTION 'export download invalid' USING ERRCODE='23514'; END IF;
  ELSE RAISE EXCEPTION 'export transition invalid' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.action IN ('CANCEL','EXPIRE','DOWNLOAD') AND (
  NEW.completed<>p.completed OR NEW.outcomes<>p.outcomes OR NEW.artifact_sha256<>p.artifact_sha256
  OR NEW.lease_id IS DISTINCT FROM p.lease_id OR NEW.lease_until IS DISTINCT FROM p.lease_until)
 THEN RAISE EXCEPTION 'export status cannot rewrite result' USING ERRCODE='23514'; END IF;
 NEW.created_at=statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER selected_export_event_guard BEFORE INSERT OR UPDATE OR DELETE ON selected_exports_exportevent
 FOR EACH ROW EXECUTE FUNCTION selected_export_event_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("selected_exports", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER selected_export_event_guard ON selected_exports_exportevent;
        DROP FUNCTION selected_export_event_guard();
        DROP TRIGGER selected_export_artifact_guard ON selected_exports_exportartifact;
        DROP FUNCTION selected_export_artifact_guard();
        DROP TRIGGER selected_export_job_guard ON selected_exports_exportjob;
        DROP FUNCTION selected_export_job_guard();
    """,
        )
    ]
