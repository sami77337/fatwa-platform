from django.db import migrations

SQL = r"""
CREATE FUNCTION upload_security_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual jsonb; submitted jsonb; previous upload_security_scanattempt%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'upload security history immutable' USING ERRCODE='23514';
 END IF;
 actual:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at','original'];
 submitted:=NEW.canonical_payload::jsonb;
 IF TG_TABLE_NAME='upload_security_scanattempt' THEN
  IF NOT submitted ? 'valid_until'
     OR (NEW.valid_until IS NULL AND submitted->'valid_until' IS DISTINCT FROM 'null'::jsonb)
     OR (NEW.valid_until IS NOT NULL AND
       (jsonb_typeof(submitted->'valid_until') IS DISTINCT FROM 'string'
        OR (submitted->>'valid_until')::timestamptz IS DISTINCT FROM NEW.valid_until))
  THEN RAISE EXCEPTION 'upload scan expiry seal invalid' USING ERRCODE='23514'; END IF;
  actual:=actual-'valid_until'; submitted:=submitted-'valid_until';
 END IF;
 IF actual IS DISTINCT FROM submitted
    OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
 THEN RAISE EXCEPTION 'upload security seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='upload_security_quarantinedfile' THEN
  IF NEW.sha256 !~ '^[a-f0-9]{64}$' OR NEW.size<1 OR NEW.size>192000
     OR octet_length(NEW.original)<>NEW.size
     OR encode(sha256(NEW.original),'hex')<>NEW.sha256
  THEN RAISE EXCEPTION 'exact bounded quarantine required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='upload_security_uploadadmission' THEN
  IF NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.case_revision<1 OR NEW.evidence_version<1
  THEN RAISE EXCEPTION 'upload admission context invalid' USING ERRCODE='23514'; END IF;
 ELSE
  PERFORM sha256 FROM upload_security_quarantinedfile WHERE sha256=NEW.file_id FOR UPDATE;
  SELECT * INTO previous FROM upload_security_scanattempt WHERE file_id=NEW.file_id ORDER BY sequence DESC LIMIT 1;
  IF NOT EXISTS(SELECT 1 FROM upload_security_uploadadmission WHERE file_id=NEW.file_id)
     OR NEW.sequence<>COALESCE(previous.sequence,0)+1
     OR NEW.previous_digest<>COALESCE(previous.digest,repeat('0',64))
  THEN RAISE EXCEPTION 'upload scan admission or predecessor invalid' USING ERRCODE='23514'; END IF;
  IF jsonb_typeof(NEW.policy) IS DISTINCT FROM 'object'
     OR NOT NEW.policy ?& ARRAY['key','timeout_seconds','validity_seconds','max_quarantined_files']
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.policy))<>4
     OR COALESCE(NEW.policy->>'key','') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR jsonb_typeof(NEW.policy->'timeout_seconds') IS DISTINCT FROM 'number'
     OR (NEW.policy->>'timeout_seconds')::numeric NOT BETWEEN 0.01 AND 30
     OR COALESCE(NEW.policy->>'validity_seconds','') !~ '^[1-9][0-9]{0,4}$'
     OR (NEW.policy->>'validity_seconds')::integer>86400
     OR COALESCE(NEW.policy->>'max_quarantined_files','') !~ '^[1-9][0-9]{0,4}$'
     OR (NEW.policy->>'max_quarantined_files')::integer>10000
  THEN RAISE EXCEPTION 'upload scan policy invalid' USING ERRCODE='23514'; END IF;
  IF NEW.scanner<>'{}'::jsonb AND (
     jsonb_typeof(NEW.scanner) IS DISTINCT FROM 'object'
     OR NOT NEW.scanner ?& ARRAY['key','engine_version','signature_version','signature_digest','configuration_digest','mode']
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.scanner))<>6
     OR COALESCE(NEW.scanner->>'key','') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR COALESCE(NEW.scanner->>'engine_version','') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR COALESCE(NEW.scanner->>'signature_version','') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR COALESCE(NEW.scanner->>'signature_digest','') !~ '^[a-f0-9]{64}$'
     OR COALESCE(NEW.scanner->>'configuration_digest','') !~ '^[a-f0-9]{64}$'
     OR COALESCE(NEW.scanner->>'mode','') NOT IN ('CONFIGURED','SYNTHETIC'))
  THEN RAISE EXCEPTION 'upload scanner identity invalid' USING ERRCODE='23514'; END IF;
  IF NEW.status='CLEAN' THEN
   IF NEW.scanner='{}'::jsonb OR NOT NEW.complete OR NEW.scanned_files<>1
      OR NEW.loaded_signatures<1 OR NEW.loaded_signatures>100000000
      OR NEW.valid_until IS NULL OR NEW.valid_until<=statement_timestamp()
      OR NEW.valid_until>statement_timestamp()+make_interval(secs=>(NEW.policy->>'validity_seconds')::integer)
      OR EXISTS(SELECT 1 FROM upload_security_scanattempt WHERE file_id=NEW.file_id AND status='BLOCKED')
   THEN RAISE EXCEPTION 'complete current clean scan required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.valid_until IS NOT NULL THEN
   RAISE EXCEPTION 'unavailable scan cannot release bytes' USING ERRCODE='23514';
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER upload_security_file_guard BEFORE INSERT OR UPDATE OR DELETE ON upload_security_quarantinedfile FOR EACH ROW EXECUTE FUNCTION upload_security_history_guard();
CREATE TRIGGER upload_security_admission_guard BEFORE INSERT OR UPDATE OR DELETE ON upload_security_uploadadmission FOR EACH ROW EXECUTE FUNCTION upload_security_history_guard();
CREATE TRIGGER upload_security_scan_guard BEFORE INSERT OR UPDATE OR DELETE ON upload_security_scanattempt FOR EACH ROW EXECUTE FUNCTION upload_security_history_guard();
"""

REVERSE = """
DROP TRIGGER upload_security_scan_guard ON upload_security_scanattempt;
DROP TRIGGER upload_security_admission_guard ON upload_security_uploadadmission;
DROP TRIGGER upload_security_file_guard ON upload_security_quarantinedfile;
DROP FUNCTION upload_security_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("upload_security", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
