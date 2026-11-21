from django.db import migrations

SQL = r"""
CREATE FUNCTION media_derivatives_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual jsonb; submitted jsonb; job media_derivatives_derivativejob%ROWTYPE;
previous media_derivatives_derivativeevent%ROWTYPE; output media_derivatives_derivedoutput%ROWTYPE;
source_case uuid; source_hash text; source_size integer; source_id uuid; source_kind text;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'derivative history immutable' USING ERRCODE='23514';
 END IF;
 actual:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at','raw'];
 submitted:=NEW.canonical_payload::jsonb;
 IF TG_TABLE_NAME='media_derivatives_derivativejob' THEN
  IF jsonb_typeof(submitted->'execute_until') IS DISTINCT FROM 'string'
     OR (submitted->>'execute_until')::timestamptz IS DISTINCT FROM NEW.execute_until
  THEN RAISE EXCEPTION 'derivative execution expiry seal invalid' USING ERRCODE='23514'; END IF;
  actual:=actual-'execute_until'; submitted:=submitted-'execute_until';
 ELSIF TG_TABLE_NAME='media_derivatives_derivativeevent' THEN
  IF NOT submitted ? 'lease_until'
     OR (NEW.lease_until IS NULL AND submitted->'lease_until' IS DISTINCT FROM 'null'::jsonb)
     OR (NEW.lease_until IS NOT NULL AND
        (jsonb_typeof(submitted->'lease_until') IS DISTINCT FROM 'string'
         OR (submitted->>'lease_until')::timestamptz IS DISTINCT FROM NEW.lease_until))
  THEN RAISE EXCEPTION 'derivative lease expiry seal invalid' USING ERRCODE='23514'; END IF;
  actual:=actual-'lease_until'; submitted:=submitted-'lease_until';
 END IF;
 IF actual IS DISTINCT FROM submitted
    OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
 THEN RAISE EXCEPTION 'derivative record seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='media_derivatives_derivativejob' THEN
  PERFORM id FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
  IF NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
     OR NEW.claims_digest !~ '^[a-f0-9]{64}$' OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.source_digest !~ '^[a-f0-9]{64}$'
     OR NEW.recipe_version<>'technical-private-v1'
     OR NEW.execute_until<=statement_timestamp()
     OR NEW.execute_until>statement_timestamp()+interval '601 seconds'
     OR (SELECT count(*) FROM media_derivatives_derivativejob WHERE case_id=NEW.case_id)>=64
  THEN RAISE EXCEPTION 'derivative request context invalid' USING ERRCODE='23514'; END IF;
  IF jsonb_typeof(NEW.source) IS DISTINCT FROM 'object'
     OR NOT NEW.source ?& ARRAY['kind','id','sha256','size','media_type','version_digest']
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.source))<>6
     OR COALESCE(NEW.source->>'sha256','') !~ '^[a-f0-9]{64}$'
     OR COALESCE(NEW.source->>'version_digest','') !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'derivative source pin invalid' USING ERRCODE='23514'; END IF;
  IF NEW.attachment_id IS NOT NULL THEN
   source_kind:='ATTACHMENT'; source_id:=NEW.attachment_id;
   SELECT case_id, sha256, size INTO source_case, source_hash, source_size FROM case_attachments_caseattachment WHERE id=source_id;
  ELSIF NEW.answer_part_id IS NOT NULL THEN
   source_kind:='ANSWER_PART'; source_id:=NEW.answer_part_id;
   SELECT a.case_id, p.sha256, p.size INTO source_case, source_hash, source_size
     FROM answer_media_answerpart p JOIN casework_answerrevision a ON a.id=p.manifest_id WHERE p.id=source_id AND p.ordinal>1;
  ELSE
   source_kind:='LIBRARY_VERSION'; source_id:=NEW.library_version_id;
   SELECT i.case_id, b.sha256, b.size INTO source_case, source_hash, source_size
     FROM research_library_libraryversion v JOIN research_library_libraryitem i ON v.item_id=i.id
     JOIN research_library_libraryblob b ON v.blob_id=b.sha256 WHERE v.id=source_id;
  END IF;
  IF source_case IS DISTINCT FROM NEW.case_id OR source_id IS NULL
     OR NEW.source->>'kind' IS DISTINCT FROM source_kind
     OR NEW.source->>'id' IS DISTINCT FROM source_id::text
     OR NEW.source->>'sha256' IS DISTINCT FROM source_hash
     OR (NEW.source->>'size')::integer IS DISTINCT FROM source_size
     OR source_size NOT BETWEEN 1 AND 192000
  THEN RAISE EXCEPTION 'exact owned original required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='media_derivatives_derivedoutput' THEN
  SELECT * INTO job FROM media_derivatives_derivativejob WHERE id=NEW.job_id FOR UPDATE;
  SELECT * INTO previous FROM media_derivatives_derivativeevent WHERE job_id=NEW.job_id ORDER BY sequence DESC LIMIT 1;
  IF previous.state IS DISTINCT FROM 'RUNNING' OR previous.attempt IS DISTINCT FROM NEW.attempt
     OR previous.lease IS DISTINCT FROM NEW.lease OR previous.lease_until<=statement_timestamp()
     OR job.execute_until<=statement_timestamp() OR NEW.recipe_version<>job.recipe_version
     OR NEW.source_digest<>job.source_digest OR NEW.sha256 !~ '^[a-f0-9]{64}$'
     OR NEW.size NOT BETWEEN 1 AND 8388608 OR octet_length(NEW.raw)<>NEW.size
     OR encode(sha256(NEW.raw),'hex')<>NEW.sha256
     OR NEW.media_type<>(CASE WHEN job.task='THUMBNAIL' THEN 'image/png' ELSE 'audio/wav' END)
     OR jsonb_typeof(NEW.metadata) IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.engine) IS DISTINCT FROM 'object'
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.engine))<>6
     OR NOT NEW.engine ?& ARRAY['mode','recipe_version','ffmpeg_version','ffmpeg_sha256','ffprobe_version','ffprobe_sha256']
     OR NEW.engine->>'mode' IS DISTINCT FROM 'LOCAL_FFMPEG'
     OR NEW.engine->>'recipe_version' IS DISTINCT FROM job.recipe_version
     OR COALESCE(NEW.engine->>'ffmpeg_sha256','') !~ '^[a-f0-9]{64}$'
     OR COALESCE(NEW.engine->>'ffprobe_sha256','') !~ '^[a-f0-9]{64}$'
     OR COALESCE(NEW.engine->>'ffmpeg_version','') NOT LIKE 'ffmpeg version %'
     OR COALESCE(NEW.engine->>'ffprobe_version','') NOT LIKE 'ffprobe version %'
  THEN RAISE EXCEPTION 'bounded exact derivative completion required' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO job FROM media_derivatives_derivativejob WHERE id=NEW.job_id FOR UPDATE;
  SELECT * INTO previous FROM media_derivatives_derivativeevent WHERE job_id=NEW.job_id ORDER BY sequence DESC LIMIT 1;
  IF NEW.sequence<>COALESCE(previous.sequence,0)+1 OR NEW.sequence>24
     OR NEW.previous_digest<>COALESCE(previous.digest,repeat('0',64))
     OR NEW.provider_id<>job.provider_id OR NEW.subject_id<>job.subject_id OR NEW.auth_epoch<>job.auth_epoch
     OR NEW.attempt>4 OR length(NEW.code)>32 OR NEW.code !~ '^[A-Z_]+$'
  THEN RAISE EXCEPTION 'derivative event predecessor invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action='CREATE' THEN
   IF previous.id IS NOT NULL OR NEW.state<>'QUEUED' OR NEW.attempt<>0
      OR NEW.lease IS NOT NULL OR NEW.lease_until IS NOT NULL OR NEW.output_id IS NOT NULL
      OR NEW.code<>'QUEUED' OR NEW.engine<>'{}'::jsonb
   THEN RAISE EXCEPTION 'derivative create invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='CLAIM' THEN
   PERFORM pg_advisory_xact_lock(761135,1);
   IF previous.state IS DISTINCT FROM 'QUEUED' OR NEW.state<>'RUNNING' OR NEW.attempt<>previous.attempt+1
      OR NEW.lease IS NULL OR NEW.lease_until IS NULL OR NEW.output_id IS NOT NULL
      OR NEW.lease_until<=statement_timestamp() OR NEW.lease_until>statement_timestamp()+interval '61 seconds'
      OR NEW.lease_until>job.execute_until OR NEW.code<>'RUNNING' OR NEW.engine<>'{}'::jsonb
      OR EXISTS(SELECT 1 FROM media_derivatives_derivativeevent e WHERE e.state='RUNNING'
        AND e.lease_until>statement_timestamp() AND NOT EXISTS(
          SELECT 1 FROM media_derivatives_derivativeevent newer WHERE newer.job_id=e.job_id AND newer.sequence>e.sequence))
   THEN RAISE EXCEPTION 'derivative current exclusive lease required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action IN ('COMPLETE','FAIL') THEN
   IF previous.state IS DISTINCT FROM 'RUNNING' OR NEW.attempt<>previous.attempt OR NEW.lease IS DISTINCT FROM previous.lease
      OR NEW.lease_until IS DISTINCT FROM previous.lease_until OR NEW.lease_until<=statement_timestamp()
      OR job.execute_until<=statement_timestamp()
   THEN RAISE EXCEPTION 'derivative stale completion refused' USING ERRCODE='23514'; END IF;
   IF NEW.action='COMPLETE' THEN
    SELECT * INTO output FROM media_derivatives_derivedoutput WHERE id=NEW.output_id;
    IF NEW.state<>'READY' OR output.job_id IS DISTINCT FROM job.id OR output.attempt IS DISTINCT FROM NEW.attempt
       OR output.lease IS DISTINCT FROM NEW.lease OR output.engine IS DISTINCT FROM NEW.engine OR NEW.code<>'READY'
    THEN RAISE EXCEPTION 'derivative exact output required' USING ERRCODE='23514'; END IF;
   ELSIF NEW.state NOT IN ('FAILED','UNAVAILABLE') OR NEW.output_id IS NOT NULL
      OR NEW.code NOT IN ('INPUT_BOUND','CANCELLED','PROCESSOR_BUSY','PROCESSOR_UNAVAILABLE','PROCESSING_TIMEOUT','PROCESSING_REJECTED') THEN
    RAISE EXCEPTION 'derivative failure invalid' USING ERRCODE='23514';
   END IF;
  ELSIF NEW.action='RETRY' THEN
   IF NOT (previous.state IN ('FAILED','UNAVAILABLE') OR (previous.state='RUNNING' AND previous.lease_until<=statement_timestamp()))
      OR NEW.state<>'QUEUED' OR NEW.attempt<>previous.attempt OR NEW.attempt>=4
      OR NEW.lease IS NOT NULL OR NEW.lease_until IS NOT NULL OR NEW.output_id IS NOT NULL
      OR NEW.code<>'REQUEUED' OR NEW.engine<>'{}'::jsonb OR job.execute_until<=statement_timestamp()
   THEN RAISE EXCEPTION 'derivative retry invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='CANCEL' THEN
   IF previous.state NOT IN ('QUEUED','RUNNING','FAILED','UNAVAILABLE') OR NEW.state<>'CANCELLED'
      OR NEW.attempt<>previous.attempt OR NEW.lease IS NOT NULL OR NEW.lease_until IS NOT NULL OR NEW.output_id IS NOT NULL
      OR NEW.code<>'USER_CANCELLED' OR NEW.engine<>'{}'::jsonb
   THEN RAISE EXCEPTION 'derivative cancel invalid' USING ERRCODE='23514'; END IF;
  ELSE RAISE EXCEPTION 'derivative event action invalid' USING ERRCODE='23514';
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER media_derivatives_job_guard BEFORE INSERT OR UPDATE OR DELETE ON media_derivatives_derivativejob FOR EACH ROW EXECUTE FUNCTION media_derivatives_history_guard();
CREATE TRIGGER media_derivatives_output_guard BEFORE INSERT OR UPDATE OR DELETE ON media_derivatives_derivedoutput FOR EACH ROW EXECUTE FUNCTION media_derivatives_history_guard();
CREATE TRIGGER media_derivatives_event_guard BEFORE INSERT OR UPDATE OR DELETE ON media_derivatives_derivativeevent FOR EACH ROW EXECUTE FUNCTION media_derivatives_history_guard();
"""
REVERSE = """
DROP TRIGGER media_derivatives_job_guard ON media_derivatives_derivativejob;
DROP TRIGGER media_derivatives_output_guard ON media_derivatives_derivedoutput;
DROP TRIGGER media_derivatives_event_guard ON media_derivatives_derivativeevent;
DROP FUNCTION media_derivatives_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("media_derivatives", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
