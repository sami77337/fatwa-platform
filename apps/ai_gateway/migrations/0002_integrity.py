from django.db import migrations

SQL = r"""
CREATE FUNCTION ai_gateway_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r ai_gateway_gatewayrun%ROWTYPE; entry jsonb; source_kind text; source_exists boolean;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'ai gateway history immutable' USING ERRCODE='23514';
 END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
 THEN RAISE EXCEPTION 'ai gateway seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='ai_gateway_gatewayrun' THEN
  IF NEW.task<>'CITATION_CANDIDATES' OR NEW.task_version<>'citation-candidates.v1'
    OR NEW.prompt_version<>'citation-locations.v1' OR NEW.schema_version<>'citation-ranges.v1'
    OR NEW.request_digest !~ '^[a-f0-9]{64}$' OR NEW.query_digest !~ '^[a-f0-9]{64}$'
    OR NEW.context_digest !~ '^[a-f0-9]{64}$'
    OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR NEW.identity_provider !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
    OR NEW.provider_mode NOT IN ('SYNTHETIC','CONFIGURED','UNCONFIGURED')
    OR (NEW.provider_mode='UNCONFIGURED' AND (NEW.provider_key<>'' OR NEW.model_id<>'' OR NEW.model_version<>'' OR NEW.adapter_version<>''))
    OR (NEW.provider_mode<>'UNCONFIGURED' AND (NEW.provider_key='' OR NEW.model_id='' OR NEW.model_version='' OR NEW.adapter_version=''))
    OR (NEW.provider_mode<>'UNCONFIGURED' AND NEW.model_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    OR jsonb_typeof(NEW.source) IS DISTINCT FROM 'object'
    OR NOT NEW.source ?& ARRAY['kind','id','case_id','digest','number','part_id','locator','external']
    OR (SELECT count(*) FROM jsonb_object_keys(NEW.source))<>8
    OR COALESCE(NEW.source->>'kind','') NOT IN ('LIBRARY','ANSWER')
    OR NEW.source->>'part_id' IS DISTINCT FROM '' OR NEW.source->'external' IS DISTINCT FROM '{}'::jsonb
    OR jsonb_typeof(NEW.source->'locator') IS DISTINCT FROM 'object'
    OR NOT (NEW.source->'locator') ?& ARRAY['mode','start','end','label','limitation']
    OR (SELECT count(*) FROM jsonb_object_keys(NEW.source->'locator'))<>5
    OR NEW.source->'locator'->>'mode' IS DISTINCT FROM 'TEXT'
    OR jsonb_typeof(NEW.source->'locator'->'start') IS DISTINCT FROM 'number'
    OR jsonb_typeof(NEW.source->'locator'->'end') IS DISTINCT FROM 'number'
    OR COALESCE(NEW.source->'locator'->>'start','') !~ '^[0-9]+$'
    OR COALESCE(NEW.source->'locator'->>'end','') !~ '^[0-9]+$'
    OR COALESCE(NEW.source->>'id','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
    OR COALESCE(NEW.source->>'case_id','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
    OR COALESCE(NEW.source->>'number','') !~ '^[1-9][0-9]{0,6}$'
    OR (NEW.source->'locator'->>'start')::integer<0
    OR (NEW.source->'locator'->>'end')::integer<=(NEW.source->'locator'->>'start')::integer
    OR (NEW.source->'locator'->>'end')::integer-(NEW.source->'locator'->>'start')::integer>4000
    OR COALESCE(NEW.source->>'digest','') !~ '^[a-f0-9]{64}$'
    OR NEW.expected_revision<1 OR NEW.expected_evidence_version<1
  THEN RAISE EXCEPTION 'ai gateway run invalid' USING ERRCODE='23514'; END IF;
  source_kind:=NEW.source->>'kind';
  IF source_kind='LIBRARY' THEN
   SELECT EXISTS(SELECT 1 FROM research_library_libraryversion v JOIN research_library_libraryitem i ON i.id=v.item_id
     WHERE v.id::text=NEW.source->>'id' AND i.case_id::text=NEW.source->>'case_id'
       AND v.number=(NEW.source->>'number')::integer AND v.digest=NEW.source->>'digest') INTO source_exists;
  ELSE
   SELECT EXISTS(SELECT 1 FROM casework_answerrevision a JOIN casework_casedecision d ON d.answer_id=a.id
     WHERE a.id::text=NEW.source->>'id' AND a.case_id::text=NEW.source->>'case_id'
       AND a.revision=(NEW.source->>'number')::integer AND a.text_sha256=NEW.source->>'digest'
       AND d.action='APPROVE') INTO source_exists;
  END IF;
  IF NOT source_exists THEN RAISE EXCEPTION 'ai gateway exact existing source required' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO r FROM ai_gateway_gatewayrun WHERE id=NEW.run_id;
  IF r.id IS NULL THEN RAISE EXCEPTION 'ai gateway attempt required' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='ai_gateway_gatewayoutcome' THEN
   IF (NEW.status='SUCCEEDED' AND (NEW.output_digest !~ '^[a-f0-9]{64}$' OR r.provider_mode='UNCONFIGURED'))
      OR (NEW.status<>'SUCCEEDED' AND NEW.output_digest<>'')
      OR (NEW.status='PROVIDER_UNAVAILABLE' AND r.provider_mode<>'UNCONFIGURED')
   THEN RAISE EXCEPTION 'ai gateway outcome invalid' USING ERRCODE='23514'; END IF;
  ELSE
   IF NOT EXISTS(SELECT 1 FROM ai_gateway_gatewayoutcome WHERE run_id=r.id AND status='SUCCEEDED')
      OR jsonb_typeof(NEW.entries) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.entries)>5
   THEN RAISE EXCEPTION 'ai gateway candidates require success' USING ERRCODE='23514'; END IF;
   FOR entry IN SELECT value FROM jsonb_array_elements(NEW.entries) LOOP
    IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
      OR NOT entry ?& ARRAY['source_id','start','end']
      OR (SELECT count(*) FROM jsonb_object_keys(entry))<>3
      OR entry->>'source_id' IS DISTINCT FROM r.source->>'id'
      OR jsonb_typeof(entry->'start') IS DISTINCT FROM 'number'
      OR jsonb_typeof(entry->'end') IS DISTINCT FROM 'number'
      OR COALESCE(entry->>'start','') !~ '^[0-9]+$' OR COALESCE(entry->>'end','') !~ '^[0-9]+$'
      OR (entry->>'start')::integer<(r.source->'locator'->>'start')::integer
      OR (entry->>'end')::integer>(r.source->'locator'->>'end')::integer
      OR (entry->>'end')::integer<=(entry->>'start')::integer
      OR (entry->>'end')::integer-(entry->>'start')::integer>1000
    THEN RAISE EXCEPTION 'ai gateway candidate invalid' USING ERRCODE='23514'; END IF;
   END LOOP;
   IF (SELECT count(*) FROM jsonb_array_elements(NEW.entries))<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.entries))
   THEN RAISE EXCEPTION 'ai gateway duplicate candidates' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER ai_gateway_run_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_gateway_gatewayrun FOR EACH ROW EXECUTE FUNCTION ai_gateway_history_guard();
CREATE TRIGGER ai_gateway_outcome_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_gateway_gatewayoutcome FOR EACH ROW EXECUTE FUNCTION ai_gateway_history_guard();
CREATE TRIGGER ai_gateway_batch_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_gateway_candidatebatch FOR EACH ROW EXECUTE FUNCTION ai_gateway_history_guard();
"""

REVERSE = """
DROP TRIGGER ai_gateway_batch_guard ON ai_gateway_candidatebatch;
DROP TRIGGER ai_gateway_outcome_guard ON ai_gateway_gatewayoutcome;
DROP TRIGGER ai_gateway_run_guard ON ai_gateway_gatewayrun;
DROP FUNCTION ai_gateway_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("ai_gateway", "0001_initial"), ("precise_citations", "0002_integrity")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
