from django.db import migrations

SQL = r"""
CREATE FUNCTION staff_sessions_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s staff_sessions_session%ROWTYPE; t staff_sessions_session%ROWTYPE;
        p staff_sessions_freshproof%ROWTYPE; r staff_sessions_sessionrevocation%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'staff session history immutable' USING ERRCODE='23514';
 END IF;
 IF jsonb_typeof(NEW.canonical_payload::jsonb) IS DISTINCT FROM 'object'
  OR (SELECT count(*) FROM jsonb_object_keys(NEW.canonical_payload::jsonb))<>(SELECT count(*) FROM jsonb_object_keys(to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']))
  OR NEW.canonical_payload::jsonb-ARRAY['expires_at','verified_at'] IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at','expires_at','verified_at']
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
 THEN RAISE EXCEPTION 'staff session seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME IN ('staff_sessions_session','staff_sessions_freshproof') THEN
  IF jsonb_typeof(NEW.canonical_payload::jsonb->'expires_at') IS DISTINCT FROM 'string'
    OR (NEW.canonical_payload::jsonb->>'expires_at')::timestamptz IS DISTINCT FROM NEW.expires_at
  THEN RAISE EXCEPTION 'staff session expiry seal invalid' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='staff_sessions_freshproof' THEN
  IF jsonb_typeof(NEW.canonical_payload::jsonb->'verified_at') IS DISTINCT FROM 'string'
    OR (NEW.canonical_payload::jsonb->>'verified_at')::timestamptz IS DISTINCT FROM NEW.verified_at
  THEN RAISE EXCEPTION 'staff verification time seal invalid' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='staff_sessions_session' THEN
  IF (NEW.surface='CASEWORK' AND NEW.role<>'MUFTI') OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
   OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
   OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
   OR NEW.browser_digest !~ '^[a-f0-9]{64}$' OR NEW.claims_digest !~ '^[a-f0-9]{64}$'
   OR NEW.runtime_digest !~ '^[a-f0-9]{64}$' OR NEW.authority_digest !~ '^[a-f0-9]{64}$'
   OR NEW.expires_at<=statement_timestamp() OR NEW.expires_at>statement_timestamp()+interval '1 hour'
  THEN RAISE EXCEPTION 'staff session record invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_sessions_freshproof' THEN
  SELECT * INTO s FROM staff_sessions_session WHERE id=NEW.session_id;
  SELECT * INTO t FROM staff_sessions_session WHERE id=NEW.target_id;
  IF s.id IS NULL OR t.id IS NULL OR NEW.operation<>'REVOKE_SESSION'
   OR NEW.target_digest<>t.digest OR NEW.challenge_digest !~ '^[a-f0-9]{64}$'
   OR NEW.authority_digest !~ '^[a-f0-9]{64}$' OR NEW.directory_digest !~ '^[a-f0-9]{64}$'
   OR NEW.method_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
   OR NEW.verified_at>statement_timestamp() OR NEW.verified_at<statement_timestamp()-interval '5 minutes'
   OR NEW.expires_at<=statement_timestamp() OR NEW.expires_at>s.expires_at
   OR NEW.expires_at>statement_timestamp()+interval '5 minutes'
   OR EXISTS(SELECT 1 FROM staff_sessions_sessionrevocation WHERE session_id IN (s.id,t.id))
  THEN RAISE EXCEPTION 'staff fresh proof invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_sessions_sessionrevocation' THEN
  SELECT * INTO s FROM staff_sessions_session WHERE id=NEW.session_id;
  SELECT * INTO t FROM staff_sessions_session WHERE id=NEW.by_session_id;
  IF s.id IS NULL OR t.id IS NULL OR (NEW.reason='LOGOUT' AND (s.id<>t.id OR NEW.proof_id IS NOT NULL))
  THEN RAISE EXCEPTION 'staff session revocation invalid' USING ERRCODE='23514'; END IF;
  IF NEW.proof_id IS NOT NULL THEN
   SELECT * INTO p FROM staff_sessions_freshproof WHERE id=NEW.proof_id;
   IF p.id IS NULL OR p.session_id<>t.id OR p.target_id<>s.id OR p.target_digest<>s.digest
    OR p.expires_at<=statement_timestamp() OR EXISTS(SELECT 1 FROM staff_sessions_proofuse WHERE proof_id=p.id)
   THEN RAISE EXCEPTION 'staff session revocation proof invalid' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  SELECT * INTO p FROM staff_sessions_freshproof WHERE id=NEW.proof_id;
  SELECT * INTO r FROM staff_sessions_sessionrevocation WHERE id=NEW.revocation_id;
  IF p.id IS NULL OR r.id IS NULL OR r.proof_id IS DISTINCT FROM p.id
   OR r.by_session_id<>p.session_id OR r.session_id<>p.target_id OR r.reason<>'USER_REVOKE'
  THEN RAISE EXCEPTION 'staff proof consumption invalid' USING ERRCODE='23514'; END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER staff_sessions_session_guard BEFORE INSERT OR UPDATE OR DELETE ON staff_sessions_session FOR EACH ROW EXECUTE FUNCTION staff_sessions_history_guard();
CREATE TRIGGER staff_sessions_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON staff_sessions_freshproof FOR EACH ROW EXECUTE FUNCTION staff_sessions_history_guard();
CREATE TRIGGER staff_sessions_revocation_guard BEFORE INSERT OR UPDATE OR DELETE ON staff_sessions_sessionrevocation FOR EACH ROW EXECUTE FUNCTION staff_sessions_history_guard();
CREATE TRIGGER staff_sessions_use_guard BEFORE INSERT OR UPDATE OR DELETE ON staff_sessions_proofuse FOR EACH ROW EXECUTE FUNCTION staff_sessions_history_guard();
"""
REVERSE = """
DROP TRIGGER staff_sessions_use_guard ON staff_sessions_proofuse;
DROP TRIGGER staff_sessions_revocation_guard ON staff_sessions_sessionrevocation;
DROP TRIGGER staff_sessions_proof_guard ON staff_sessions_freshproof;
DROP TRIGGER staff_sessions_session_guard ON staff_sessions_session;
DROP FUNCTION staff_sessions_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("staff_sessions", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
