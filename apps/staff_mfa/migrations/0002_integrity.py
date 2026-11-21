from django.db import migrations

TABLES = (
    "account",
    "challenge",
    "factor",
    "proof",
    "attempt",
    "recoverycode",
    "factorrevocation",
    "recoveryuse",
    "sessionassurance",
)

SQL = r"""
CREATE FUNCTION staff_mfa_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE raw jsonb; sealed jsonb; k text;
 c staff_mfa_challenge%ROWTYPE; f staff_mfa_factor%ROWTYPE; p staff_mfa_proof%ROWTYPE;
 r staff_mfa_recoverycode%ROWTYPE; v staff_mfa_factorrevocation%ROWTYPE;
 s staff_sessions_session%ROWTYPE; a staff_mfa_account%ROWTYPE;
 dates text[]:=ARRAY['expires_at','primary_verified_at','actor_deadline','verified_at'];
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'staff MFA history immutable' USING ERRCODE='23514';
 END IF;
 raw:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 sealed:=NEW.canonical_payload::jsonb;
 IF jsonb_typeof(sealed) IS DISTINCT FROM 'object'
  OR (SELECT count(*) FROM jsonb_object_keys(sealed))<>(SELECT count(*) FROM jsonb_object_keys(raw))
  OR sealed-dates IS DISTINCT FROM raw-dates
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
 THEN RAISE EXCEPTION 'staff MFA seal invalid' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY dates LOOP
  IF raw ? k AND (jsonb_typeof(sealed->k) IS DISTINCT FROM 'string'
   OR (sealed->>k)::timestamptz IS DISTINCT FROM (raw->>k)::timestamptz)
  THEN RAISE EXCEPTION 'staff MFA date seal invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF TG_TABLE_NAME='staff_mfa_account' THEN
  IF NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
   OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  THEN RAISE EXCEPTION 'staff MFA account invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_challenge' THEN
  SELECT * INTO a FROM staff_mfa_account WHERE id=NEW.account_id FOR UPDATE;
  IF a.id IS NULL OR NEW.role NOT IN ('MUFTI','ORGANIZER_ADMIN','ORGANIZER')
   OR (NEW.surface='CASEWORK' AND NEW.role<>'MUFTI')
   OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
   OR NEW.primary_method !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
   OR NEW.primary_verified_at>statement_timestamp()
   OR NEW.primary_verified_at<statement_timestamp()-interval '20 seconds'
   OR NEW.expires_at<=statement_timestamp() OR NEW.expires_at>statement_timestamp()+interval '5 minutes'
   OR NEW.actor_deadline<NEW.expires_at OR NEW.actor_deadline>statement_timestamp()+interval '1 hour'
  THEN RAISE EXCEPTION 'staff MFA primary challenge invalid' USING ERRCODE='23514'; END IF;
  FOREACH k IN ARRAY ARRAY['claims_digest','browser_digest','authority_digest','directory_digest',
                           'runtime_digest','key_digest','nonce_digest'] LOOP
   IF raw->>k !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'staff MFA challenge pin invalid' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF NEW.factor_id IS NOT NULL THEN
   SELECT * INTO f FROM staff_mfa_factor WHERE id=NEW.factor_id;
   IF f.id IS NULL OR f.account_id<>a.id OR f.digest<>NEW.factor_digest
   THEN RAISE EXCEPTION 'staff MFA challenge factor invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.factor_digest<>'' OR NEW.purpose<>'LOGIN' THEN
   RAISE EXCEPTION 'staff MFA initial challenge invalid' USING ERRCODE='23514';
  END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_factor' THEN
  SELECT * INTO c FROM staff_mfa_challenge WHERE id=NEW.challenge_id;
  PERFORM 1 FROM staff_mfa_account WHERE id=NEW.account_id FOR UPDATE;
  IF c.id IS NULL OR c.account_id<>NEW.account_id OR c.purpose<>'LOGIN'
   OR c.expires_at<=statement_timestamp() OR NEW.key_digest<>c.key_digest
   OR NEW.runtime_digest<>c.runtime_digest OR NEW.secret_binding !~ '^[a-f0-9]{64}$'
   OR length(NEW.secret_ciphertext) NOT BETWEEN 100 AND 1024
   OR EXISTS(SELECT 1 FROM staff_mfa_proof WHERE challenge_id=c.id)
   OR EXISTS(SELECT 1 FROM staff_mfa_factor f0 JOIN staff_mfa_proof p0 ON p0.factor_id=f0.id
             WHERE f0.account_id=NEW.account_id AND p0.purpose='ENROLL'
             AND NOT EXISTS(SELECT 1 FROM staff_mfa_factorrevocation v0 WHERE v0.factor_id=f0.id))
   OR (EXISTS(SELECT 1 FROM staff_mfa_factor f0 JOIN staff_mfa_proof p0 ON p0.factor_id=f0.id
              WHERE f0.account_id=NEW.account_id AND p0.purpose='ENROLL')
       AND NOT EXISTS(SELECT 1 FROM staff_mfa_recoveryuse WHERE challenge_id=c.id))
   OR (c.factor_id IS NOT NULL AND c.factor_id IS DISTINCT FROM (
       SELECT f0.id FROM staff_mfa_factor f0 JOIN staff_mfa_proof p0 ON p0.factor_id=f0.id
       WHERE f0.account_id=NEW.account_id AND p0.purpose='ENROLL'
       ORDER BY p0.created_at DESC,f0.id DESC LIMIT 1))
  THEN RAISE EXCEPTION 'staff MFA enrollment invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_proof' THEN
  SELECT * INTO c FROM staff_mfa_challenge WHERE id=NEW.challenge_id;
  SELECT * INTO f FROM staff_mfa_factor WHERE id=NEW.factor_id;
  PERFORM 1 FROM staff_mfa_account WHERE id=NEW.account_id FOR UPDATE;
  IF c.id IS NULL OR f.id IS NULL OR c.account_id<>NEW.account_id OR f.account_id<>NEW.account_id
   OR c.expires_at<=statement_timestamp() OR NEW.verified_at>statement_timestamp()
   OR NEW.verified_at<statement_timestamp()-interval '5 minutes'
   OR NEW.expires_at<=statement_timestamp() OR NEW.expires_at>statement_timestamp()+interval '15 minutes'
   OR NEW.expires_at>c.actor_deadline
   OR EXISTS(SELECT 1 FROM staff_mfa_factorrevocation WHERE factor_id=f.id)
   OR (NEW.purpose='ENROLL' AND (f.challenge_id<>c.id OR c.purpose<>'LOGIN'))
   OR (NEW.purpose<>'ENROLL' AND (c.factor_id IS DISTINCT FROM f.id OR c.purpose<>NEW.purpose))
  THEN RAISE EXCEPTION 'staff MFA proof invalid' USING ERRCODE='23514'; END IF;
  IF NEW.purpose='ENROLL' AND EXISTS(
    SELECT 1 FROM staff_mfa_factor f0 JOIN staff_mfa_proof p0 ON p0.factor_id=f0.id
    WHERE f0.account_id=NEW.account_id AND f0.id<>f.id AND p0.purpose='ENROLL'
     AND NOT EXISTS(SELECT 1 FROM staff_mfa_factorrevocation v0 WHERE v0.factor_id=f0.id))
  THEN RAISE EXCEPTION 'staff MFA factor already active' USING ERRCODE='23514'; END IF;
  IF NEW.purpose='ENROLL' AND EXISTS(
    SELECT 1 FROM staff_mfa_factor f0 JOIN staff_mfa_proof p0 ON p0.factor_id=f0.id
    WHERE f0.account_id=NEW.account_id AND p0.purpose='ENROLL') AND (
     NOT EXISTS(SELECT 1 FROM staff_mfa_recoveryuse WHERE challenge_id=c.id)
     OR c.factor_id IS DISTINCT FROM (SELECT f0.id FROM staff_mfa_factor f0
       JOIN staff_mfa_proof p0 ON p0.factor_id=f0.id
       WHERE f0.account_id=NEW.account_id AND p0.purpose='ENROLL'
       ORDER BY p0.created_at DESC,f0.id DESC LIMIT 1))
  THEN RAISE EXCEPTION 'staff MFA recovery generation stale' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_attempt' THEN
  SELECT * INTO c FROM staff_mfa_challenge WHERE id=NEW.challenge_id;
  PERFORM 1 FROM staff_mfa_account WHERE id=NEW.account_id FOR UPDATE;
  IF c.id IS NULL OR c.account_id<>NEW.account_id
  THEN RAISE EXCEPTION 'staff MFA attempt owner invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_recoverycode' THEN
  SELECT * INTO p FROM staff_mfa_proof WHERE id=NEW.activation_id;
  IF p.id IS NULL OR p.account_id<>NEW.account_id OR p.factor_id<>NEW.factor_id OR p.purpose<>'ENROLL'
   OR NEW.slot>9 OR NEW.code_digest !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'staff MFA recovery code invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_factorrevocation' THEN
  SELECT * INTO f FROM staff_mfa_factor WHERE id=NEW.factor_id;
  SELECT * INTO c FROM staff_mfa_challenge WHERE id=NEW.challenge_id;
  PERFORM 1 FROM staff_mfa_account WHERE id=f.account_id FOR UPDATE;
  IF f.id IS NULL OR c.id IS NULL OR f.account_id<>c.account_id
   OR c.factor_id IS DISTINCT FROM f.id OR c.expires_at<=statement_timestamp()
  THEN RAISE EXCEPTION 'staff MFA revocation owner invalid' USING ERRCODE='23514'; END IF;
  IF NEW.reason='USER_REVOKE' THEN
   SELECT * INTO p FROM staff_mfa_proof WHERE id=NEW.proof_id;
   IF p.id IS NULL OR p.factor_id<>f.id OR p.challenge_id<>c.id OR p.purpose<>'REVOKE'
   THEN RAISE EXCEPTION 'staff MFA revocation proof invalid' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO r FROM staff_mfa_recoverycode WHERE id=NEW.recovery_code_id;
   IF r.id IS NULL OR r.factor_id<>f.id OR r.account_id<>c.account_id OR c.purpose<>'LOGIN'
    OR EXISTS(SELECT 1 FROM staff_mfa_recoveryuse WHERE code_id=r.id)
   THEN RAISE EXCEPTION 'staff MFA recovery ownership invalid' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='staff_mfa_recoveryuse' THEN
  SELECT * INTO r FROM staff_mfa_recoverycode WHERE id=NEW.code_id;
  SELECT * INTO c FROM staff_mfa_challenge WHERE id=NEW.challenge_id;
  SELECT * INTO v FROM staff_mfa_factorrevocation WHERE id=NEW.revocation_id;
  IF r.id IS NULL OR c.id IS NULL OR v.id IS NULL OR r.account_id<>c.account_id
   OR c.factor_id IS DISTINCT FROM r.factor_id OR v.factor_id<>r.factor_id OR c.purpose<>'LOGIN'
   OR c.expires_at<=statement_timestamp() OR EXISTS(SELECT 1 FROM staff_mfa_proof WHERE challenge_id=c.id)
  THEN RAISE EXCEPTION 'staff MFA recovery consumption invalid' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO s FROM staff_sessions_session WHERE id=NEW.session_id;
  SELECT * INTO p FROM staff_mfa_proof WHERE id=NEW.proof_id;
  SELECT * INTO c FROM staff_mfa_challenge WHERE id=p.challenge_id;
  SELECT * INTO a FROM staff_mfa_account WHERE id=p.account_id;
  IF s.id IS NULL OR p.id IS NULL OR c.id IS NULL OR a.id IS NULL
   OR p.purpose NOT IN ('ENROLL','LOGIN') OR s.provider_id<>a.provider_id OR s.subject_id<>a.subject_id
   OR s.role<>c.role OR s.auth_epoch<>c.auth_epoch OR s.surface<>c.surface OR s.claims_digest<>c.claims_digest
   OR s.runtime_digest<>c.runtime_digest OR NEW.expires_at>s.expires_at OR NEW.expires_at>p.expires_at
   OR NEW.expires_at<=statement_timestamp() OR c.expires_at<=statement_timestamp()
   OR EXISTS(SELECT 1 FROM staff_mfa_factorrevocation WHERE factor_id=p.factor_id)
  THEN RAISE EXCEPTION 'staff MFA session assurance invalid' USING ERRCODE='23514'; END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
"""
SQL += "\n".join(
    f"CREATE TRIGGER staff_mfa_{name}_guard BEFORE INSERT OR UPDATE OR DELETE ON staff_mfa_{name} "
    "FOR EACH ROW EXECUTE FUNCTION staff_mfa_history_guard();"
    for name in TABLES
)
REVERSE = "\n".join(
    f"DROP TRIGGER staff_mfa_{name}_guard ON staff_mfa_{name};" for name in reversed(TABLES)
)
REVERSE += "\nDROP FUNCTION staff_mfa_history_guard();"


class Migration(migrations.Migration):
    dependencies = [("staff_mfa", "0001_initial"), ("staff_sessions", "0002_integrity")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
