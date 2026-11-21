from django.db import migrations

SQL = r"""
CREATE FUNCTION dm_clear_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous record; expected jsonb; actual jsonb; item jsonb; owner_case uuid; owner_digest text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'derived_clear_history_immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(443,509);
 SELECT * INTO previous FROM derived_maintenance_derivativeclear ORDER BY sequence DESC LIMIT 1;
 IF NEW.sequence IS DISTINCT FROM coalesce(previous.sequence,0)+1
  OR NEW.previous_digest IS DISTINCT FROM coalesce(previous.digest,repeat('0',64))
  OR (previous.id IS NOT NULL AND NEW.ledger_id IS DISTINCT FROM previous.ledger_id)
  OR NOT (NEW.header_digest ~ '^[a-f0-9]{64}$' AND NEW.previous_digest ~ '^[a-f0-9]{64}$'
          AND NEW.reason_sha256 ~ '^[a-f0-9]{64}$' AND NEW.digest ~ '^[a-f0-9]{64}$') IS TRUE
  OR NOT (length(btrim(NEW.provider_id))>0 AND length(btrim(NEW.subject_id))>0
          AND length(btrim(NEW.auth_epoch))>0 AND length(btrim(NEW.applied_provider_id))>0
          AND length(btrim(NEW.applied_subject_id))>0 AND length(btrim(NEW.applied_auth_epoch))>0) IS TRUE
  OR NOT (length(NEW.reason)<=1000 AND length(NEW.recovery_reason)<=1000) IS TRUE
  OR NOT ((NEW.recovered AND NEW.reason='' AND length(btrim(NEW.recovery_reason))>0)
    OR (NOT NEW.recovered AND length(btrim(NEW.reason))>0 AND NEW.recovery_reason=''
      AND NEW.provider_id=NEW.applied_provider_id AND NEW.subject_id=NEW.applied_subject_id
      AND NEW.role=NEW.applied_role AND NEW.auth_epoch=NEW.applied_auth_epoch)) IS TRUE
  OR (NEW.reason<>'' AND encode(sha256(convert_to(NEW.reason,'UTF8')),'hex') IS DISTINCT FROM NEW.reason_sha256)
  OR NEW.occurred_at > clock_timestamp()+interval '1 minute'
 THEN RAISE EXCEPTION 'derived_clear_record_invalid' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'derived_payload_manifest_invalid' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(NEW.payload) NOT BETWEEN 1 AND 512
  OR (NEW.kind='AI_CANDIDATES' AND jsonb_array_length(NEW.payload)<>1)
 THEN RAISE EXCEPTION 'derived_payload_manifest_invalid' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.payload) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'derived_payload_manifest_invalid' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(item))<>2 OR NOT (item ?& ARRAY['id','digest'])
   OR jsonb_typeof(item->'id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(item->'digest') IS DISTINCT FROM 'string'
   OR NOT (item->>'id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$') IS TRUE
   OR NOT (item->>'digest' ~ '^[a-f0-9]{64}$') IS TRUE
  THEN RAISE EXCEPTION 'derived_payload_manifest_invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT e.value->>'id') FROM jsonb_array_elements(NEW.payload) e(value))<>jsonb_array_length(NEW.payload)
  OR (SELECT jsonb_agg(e.value ORDER BY e.value->>'id') FROM jsonb_array_elements(NEW.payload) e(value)) IS DISTINCT FROM NEW.payload
 THEN RAISE EXCEPTION 'derived_payload_manifest_invalid' USING ERRCODE='23514'; END IF;
 IF NEW.kind='SEARCH_INDEX' THEN
  SELECT case_id,digest INTO owner_case,owner_digest FROM canonical_search_searchgeneration WHERE id=NEW.target_id;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id::text,'digest',digest) ORDER BY id),'[]'::jsonb)
    INTO actual FROM canonical_search_searchdocument WHERE generation_id=NEW.target_id;
 ELSIF NEW.kind='AI_CANDIDATES' THEN
  SELECT r.case_id,r.digest INTO owner_case,owner_digest FROM ai_gateway_gatewayrun r
   JOIN ai_gateway_gatewayoutcome o ON o.run_id=r.id AND o.status='SUCCEEDED' WHERE r.id=NEW.target_id;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id::text,'digest',digest) ORDER BY id),'[]'::jsonb)
    INTO actual FROM ai_gateway_candidatebatch WHERE run_id=NEW.target_id;
 ELSE RAISE EXCEPTION 'derived_payload_owner_invalid' USING ERRCODE='23514'; END IF;
 IF owner_case IS DISTINCT FROM NEW.case_id OR owner_digest IS DISTINCT FROM NEW.header_digest
   OR (actual IS DISTINCT FROM NEW.payload AND NOT (NEW.recovered AND actual='[]'::jsonb))
 THEN RAISE EXCEPTION 'derived_exact_payload_required' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object('id',NEW.id::text,'ledger_id',NEW.ledger_id::text,'sequence',NEW.sequence,
  'previous_digest',NEW.previous_digest,'kind',NEW.kind,'target_id',NEW.target_id::text,
  'header_digest',NEW.header_digest,'case_id',NEW.case_id::text,'payload',NEW.payload,
  'provider_id',NEW.provider_id,'subject_id',NEW.subject_id,'role',NEW.role,'auth_epoch',NEW.auth_epoch,
  'reason_sha256',NEW.reason_sha256,
  'occurred_at',to_char(NEW.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM expected
  OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex') IS DISTINCT FROM NEW.digest
 THEN RAISE EXCEPTION 'derived_clear_seal_invalid' USING ERRCODE='23514'; END IF;
 NEW.transaction_id:=txid_current(); NEW.applied_at:=clock_timestamp(); RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION cs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' AND TG_TABLE_NAME='canonical_search_searchdocument' THEN
  IF EXISTS(SELECT 1 FROM derived_maintenance_derivativeclear d WHERE d.kind='SEARCH_INDEX'
   AND d.target_id=OLD.generation_id AND d.transaction_id=txid_current()
   AND d.payload @> jsonb_build_array(jsonb_build_object('id',OLD.id::text,'digest',OLD.digest)))
  THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'search generations are immutable derived history' USING ERRCODE='23514';
END $$;

CREATE FUNCTION dm_payload_delete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM derived_maintenance_derivativeclear d WHERE d.kind='AI_CANDIDATES'
  AND d.target_id=OLD.run_id AND d.transaction_id=txid_current()
  AND d.payload @> jsonb_build_array(jsonb_build_object('id',OLD.id::text,'digest',OLD.digest)))
 THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'derived_exact_clearance_required' USING ERRCODE='23514';
END $$;

CREATE FUNCTION dm_prevent_payload_revival() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_kind text; owner_id uuid;
BEGIN
 IF TG_TABLE_NAME='canonical_search_searchdocument' THEN owner_kind:='SEARCH_INDEX'; owner_id:=NEW.generation_id;
 ELSE owner_kind:='AI_CANDIDATES'; owner_id:=NEW.run_id; END IF;
 IF EXISTS(SELECT 1 FROM derived_maintenance_derivativeclear WHERE kind=owner_kind AND target_id=owner_id)
 THEN RAISE EXCEPTION 'derived_cleared_payload_cannot_return' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION dm_clear_payload() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.kind='SEARCH_INDEX' THEN DELETE FROM canonical_search_searchdocument WHERE generation_id=NEW.target_id;
 ELSE DELETE FROM ai_gateway_candidatebatch WHERE run_id=NEW.target_id; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION dm_rebuild_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent record; owner_case uuid; owner_digest text; owner_subject text; owner_provider text; owner_epoch text; owner_status text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'derived_rebuild_history_immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO parent FROM derived_maintenance_derivativeclear WHERE id=NEW.clearance_id;
 IF parent.id IS NULL OR NEW.child_id=parent.target_id OR NEW.role<>'MUFTI'
  OR NOT (length(btrim(NEW.reason)) BETWEEN 1 AND 1000) IS TRUE
  OR NEW.canonical_payload::jsonb IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
  OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex') IS DISTINCT FROM NEW.digest
 THEN RAISE EXCEPTION 'derived_rebuild_record_invalid' USING ERRCODE='23514'; END IF;
 IF parent.kind='SEARCH_INDEX' THEN
  SELECT case_id,digest,subject_id,provider_id,auth_epoch,'SUCCEEDED'
   INTO owner_case,owner_digest,owner_subject,owner_provider,owner_epoch,owner_status
   FROM canonical_search_searchgeneration WHERE id=NEW.child_id;
 ELSE
  SELECT r.case_id,r.digest,r.subject_id,r.identity_provider,r.auth_epoch,o.status
   INTO owner_case,owner_digest,owner_subject,owner_provider,owner_epoch,owner_status
   FROM ai_gateway_gatewayrun r JOIN ai_gateway_gatewayoutcome o ON o.run_id=r.id WHERE r.id=NEW.child_id;
 END IF;
 IF owner_case IS DISTINCT FROM parent.case_id OR owner_digest IS DISTINCT FROM NEW.child_digest
  OR owner_subject IS DISTINCT FROM NEW.subject_id OR owner_provider IS DISTINCT FROM NEW.provider_id
  OR owner_epoch IS DISTINCT FROM NEW.auth_epoch OR owner_status IS DISTINCT FROM NEW.status
 THEN RAISE EXCEPTION 'derived_rebuild_owner_mismatch' USING ERRCODE='23514'; END IF;
 NEW.created_at:=clock_timestamp(); RETURN NEW;
END $$;

CREATE TRIGGER dm_clear_guard BEFORE INSERT OR UPDATE OR DELETE ON derived_maintenance_derivativeclear
 FOR EACH ROW EXECUTE FUNCTION dm_clear_guard();
CREATE TRIGGER dm_clear_payload AFTER INSERT ON derived_maintenance_derivativeclear
 FOR EACH ROW EXECUTE FUNCTION dm_clear_payload();
CREATE TRIGGER dm_rebuild_guard BEFORE INSERT OR UPDATE OR DELETE ON derived_maintenance_derivativerebuild
 FOR EACH ROW EXECUTE FUNCTION dm_rebuild_guard();
DROP TRIGGER ai_gateway_batch_guard ON ai_gateway_candidatebatch;
CREATE TRIGGER ai_gateway_batch_guard BEFORE INSERT OR UPDATE ON ai_gateway_candidatebatch
 FOR EACH ROW EXECUTE FUNCTION ai_gateway_history_guard();
CREATE TRIGGER dm_candidate_delete BEFORE DELETE ON ai_gateway_candidatebatch
 FOR EACH ROW EXECUTE FUNCTION dm_payload_delete_guard();
CREATE TRIGGER dm_candidate_revival BEFORE INSERT ON ai_gateway_candidatebatch
 FOR EACH ROW EXECUTE FUNCTION dm_prevent_payload_revival();
CREATE TRIGGER dm_document_revival BEFORE INSERT ON canonical_search_searchdocument
 FOR EACH ROW EXECUTE FUNCTION dm_prevent_payload_revival();
"""


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM derived_maintenance_derivativeclear)")
        if cursor.fetchone()[0]:
            raise RuntimeError("derived_populated_clearances_cannot_be_removed")
        cursor.execute("""
DROP TRIGGER dm_document_revival ON canonical_search_searchdocument;
DROP TRIGGER dm_candidate_revival ON ai_gateway_candidatebatch;
DROP TRIGGER dm_candidate_delete ON ai_gateway_candidatebatch;
DROP TRIGGER ai_gateway_batch_guard ON ai_gateway_candidatebatch;
CREATE TRIGGER ai_gateway_batch_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_gateway_candidatebatch
 FOR EACH ROW EXECUTE FUNCTION ai_gateway_history_guard();
DROP TRIGGER dm_rebuild_guard ON derived_maintenance_derivativerebuild;
DROP TRIGGER dm_clear_payload ON derived_maintenance_derivativeclear;
DROP TRIGGER dm_clear_guard ON derived_maintenance_derivativeclear;
DROP FUNCTION dm_rebuild_guard(); DROP FUNCTION dm_clear_payload();
DROP FUNCTION dm_prevent_payload_revival(); DROP FUNCTION dm_payload_delete_guard(); DROP FUNCTION dm_clear_guard();
CREATE OR REPLACE FUNCTION cs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'search generations are immutable derived history' USING ERRCODE='23514'; END $$;
""")


class Migration(migrations.Migration):
    dependencies = [
        ("derived_maintenance", "0001_initial"),
        ("canonical_search", "0006_governance_integrity"),
        ("ai_gateway", "0002_integrity"),
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, reverse),
    ]
