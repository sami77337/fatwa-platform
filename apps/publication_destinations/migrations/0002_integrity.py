"""Independent immutable source/version chains and bounded simulation transitions."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION pd_source_pin(identifier uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('id',e.id,'sha256',e.content_sha256,'number',e.number,
  'case_id',e.case_id,'answer_id',e.answer_id,'answer_sha256',a.text_sha256,
  'decision_id',e.decision_id,'evidence_version',e.evidence_version,
  'review_id',r.id,'approval_id',p.id)
 FROM experimental_publication_publicationedition e
 JOIN casework_answerrevision a ON a.id=e.answer_id
 JOIN experimental_publication_publicationaction r ON r.edition_id=e.id AND r.action='REVIEW'
 JOIN experimental_publication_publicationaction p ON p.edition_id=e.id AND p.action='APPROVE'
 WHERE e.id=identifier
$$;

CREATE FUNCTION pd_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'destination record immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF (SELECT count(*) FROM publication_destinations_destinationrecord WHERE case_id=NEW.case_id)>=2
  OR NEW.destination NOT IN ('WEBSITE','TELEGRAM_CHANNEL') THEN
  RAISE EXCEPTION 'destination record scope invalid' USING ERRCODE='23514'; END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER pd_record_guard BEFORE INSERT OR UPDATE OR DELETE ON publication_destinations_destinationrecord FOR EACH ROW EXECUTE FUNCTION pd_record_guard();

CREATE FUNCTION pd_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; rec publication_destinations_destinationrecord%ROWTYPE;
 v publication_destinations_destinationversion%ROWTYPE; prior publication_destinations_destinationversion%ROWTYPE;
 e experimental_publication_publicationedition%ROWTYPE; c casework_case%ROWTYPE;
 dec casework_casedecision%ROWTYPE; source_reviewer experimental_publication_publicationaction%ROWTYPE;
 source_approval experimental_publication_publicationaction%ROWTYPE;
 reviewer publication_destinations_destinationevent%ROWTYPE;
 prep publication_destinations_destinationevent%ROWTYPE;
 previous_event publication_destinations_destinationevent%ROWTYPE;
 profile jsonb; expected jsonb; n integer; state text; allowed boolean;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'destination history immutable' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 IF TG_TABLE_NAME='publication_destinations_destinationevent' THEN
  IF NEW.valid_until IS NOT NULL THEN
   body:=jsonb_set(body,'{valid_until}',to_jsonb(to_char(NEW.valid_until AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
  END IF;
 END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM body
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.request_sha256 !~ '^[a-f0-9]{64}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR btrim(NEW.note)='' OR length(NEW.note)>1000 THEN
  RAISE EXCEPTION 'destination seal invalid' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 IF TG_TABLE_NAME='publication_destinations_destinationversion' THEN
  SELECT * INTO rec FROM publication_destinations_destinationrecord WHERE id=NEW.record_id;
  SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=NEW.source_id;
 ELSE
  SELECT * INTO v FROM publication_destinations_destinationversion WHERE id=NEW.version_id;
  SELECT * INTO rec FROM publication_destinations_destinationrecord WHERE id=v.record_id;
  SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=v.source_id;
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=rec.case_id FOR UPDATE;
 SELECT * INTO dec FROM casework_casedecision WHERE id=e.decision_id;
 SELECT * INTO source_reviewer FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='REVIEW';
 SELECT * INTO source_approval FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='APPROVE';
 IF c.id IS NULL OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version OR e.case_id<>c.id THEN
  RAISE EXCEPTION 'destination canonical pins invalid' USING ERRCODE='23514'; END IF;
 -- Exact independent source approval, deliberately no global latest-edition rule.
 IF source_reviewer.id IS NULL OR source_approval.id IS NULL
  OR (source_approval.provider_id,source_approval.subject_id) IN
   ((e.provider_id,e.subject_id),(source_reviewer.provider_id,source_reviewer.subject_id),(dec.provider_id,dec.subject_id)) THEN
  RAISE EXCEPTION 'destination independent public source required' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='publication_destinations_destinationversion' THEN
  SELECT * INTO prior FROM publication_destinations_destinationversion WHERE record_id=rec.id ORDER BY number DESC LIMIT 1;
  profile:=NEW.profile_payload::jsonb;
  expected:=jsonb_build_object('schema','fatwa.destination-publication-plan.v1','mode','SYNTHETIC_ONLY',
   'record_id',rec.id,'version_id',NEW.id,'version',NEW.number,'destination',rec.destination,
   'profile',profile,'source',pd_source_pin(e.id),'external_publication_verified',false,
   'public_copy',jsonb_build_object('title',e.title,'category',e.category,'body',e.body,'citations',e.citations));
  IF NEW.number<>coalesce(prior.number,0)+1 OR NEW.previous_digest<>coalesce(prior.digest,repeat('0',64))
   OR NEW.source_pins IS DISTINCT FROM pd_source_pin(e.id)
   OR NEW.plan_payload::jsonb IS DISTINCT FROM expected
   OR NEW.profile_sha256<>encode(sha256(convert_to(NEW.profile_payload,'UTF8')),'hex')
   OR NEW.plan_sha256<>encode(sha256(convert_to(NEW.plan_payload,'UTF8')),'hex')
   OR jsonb_typeof(profile) IS DISTINCT FROM 'object' OR jsonb_object_length_compat(profile)<>5
   OR NOT profile ?& ARRAY['key','mode','content','revision','max_chars']
   OR (profile->>'key') IS DISTINCT FROM rec.destination OR (profile->>'mode') IS DISTINCT FROM 'SYNTHETIC_ONLY'
   OR (profile->>'content') IS DISTINCT FROM 'REVIEWED_PUBLIC_EDITION'
   OR coalesce(profile->>'revision','') !~ '^[A-Za-z0-9._:-]{1,64}$'
   OR coalesce(profile->>'max_chars','') !~ '^[0-9]{1,5}$'
   OR (profile->>'max_chars')::integer NOT BETWEEN 1 AND 24000
   OR length(e.title)+length(e.category)+length(e.body)>(profile->>'max_chars')::integer
   OR c.stage<>'ANSWERED' OR c.approved_answer_id<>e.answer_id OR e.evidence_version<>c.evidence_version
   OR dec.action<>'APPROVE' OR dec.answer_id<>e.answer_id
   OR EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='WITHDRAW')
   OR EXISTS(SELECT 1 FROM publication_destinations_destinationevent WHERE request_key=NEW.request_key) THEN
   RAISE EXCEPTION 'destination exact version or plan invalid' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT count(*) INTO n FROM publication_destinations_destinationevent WHERE version_id=v.id;
  SELECT * INTO previous_event FROM publication_destinations_destinationevent WHERE version_id=v.id ORDER BY sequence DESC LIMIT 1;
  SELECT * INTO reviewer FROM publication_destinations_destinationevent WHERE version_id=v.id AND action='REVIEW';
  SELECT * INTO prep FROM publication_destinations_destinationevent WHERE version_id=v.id AND action='PREPARE';
  state:=coalesce(previous_event.action,'SELECTED');
  allowed:=CASE NEW.action
   WHEN 'REVIEW' THEN state='SELECTED'
   WHEN 'APPROVE' THEN state='REVIEW'
   WHEN 'PREPARE' THEN state='APPROVE'
   WHEN 'ACCEPTED' THEN state='PREPARE'
   WHEN 'SIMULATED_PUBLISHED' THEN state IN ('PREPARE','ACCEPTED')
   WHEN 'FAILED' THEN state IN ('PREPARE','ACCEPTED')
   WHEN 'WITHDRAW' THEN state IN ('SELECTED','REVIEW','APPROVE','PREPARE','ACCEPTED','SIMULATED_PUBLISHED','FAILED')
   ELSE false END;
  IF allowed IS NOT TRUE OR NEW.sequence<>n+1 OR NEW.previous_digest<>coalesce(previous_event.digest,v.digest)
   OR NEW.plan_sha256<>v.plan_sha256
   OR EXISTS(SELECT 1 FROM publication_destinations_destinationversion WHERE request_key=NEW.request_key)
   OR (NEW.action<>'WITHDRAW' AND (
     EXISTS(SELECT 1 FROM publication_destinations_destinationversion WHERE record_id=rec.id AND number>v.number)
     OR c.stage<>'ANSWERED' OR c.approved_answer_id<>e.answer_id OR e.evidence_version<>c.evidence_version
     OR dec.action<>'APPROVE' OR dec.answer_id<>e.answer_id
     OR EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='WITHDRAW')))
   OR (NEW.action='REVIEW' AND (NEW.provider_id,NEW.subject_id)=(v.provider_id,v.subject_id))
   OR (NEW.action IN ('APPROVE','PREPARE') AND (reviewer.id IS NULL OR (NEW.provider_id,NEW.subject_id) IN
      ((v.provider_id,v.subject_id),(reviewer.provider_id,reviewer.subject_id),(dec.provider_id,dec.subject_id))))
   OR (NEW.action='PREPARE' AND (NEW.valid_until<=clock_timestamp() OR NEW.valid_until>clock_timestamp()+interval '15 minutes')) THEN
   RAISE EXCEPTION 'destination transition or independent actor invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action IN ('ACCEPTED','SIMULATED_PUBLISHED','FAILED') THEN
   expected:=NEW.provider_envelope;
   IF prep.id IS NULL OR prep.valid_until<=clock_timestamp()
    OR jsonb_typeof(expected) IS DISTINCT FROM 'object' OR jsonb_object_length_compat(expected)<>19
    OR NOT expected ?& ARRAY['issuer','audience','key_id','provider','event_id','record_id','version_id','version_sha256','preparation_id','preparation_sha256','destination','profile_sha256','plan_sha256','source_id','source_sha256','reported','issued_at','expires_at','signature_b64url']
    OR (expected->>'event_id') IS DISTINCT FROM NEW.provider_event_id::text
    OR (expected->>'record_id') IS DISTINCT FROM rec.id::text OR (expected->>'version_id') IS DISTINCT FROM v.id::text
    OR (expected->>'version_sha256') IS DISTINCT FROM v.digest
    OR (expected->>'preparation_id') IS DISTINCT FROM prep.id::text OR (expected->>'preparation_sha256') IS DISTINCT FROM prep.digest
    OR (expected->>'destination') IS DISTINCT FROM rec.destination
    OR (expected->>'profile_sha256') IS DISTINCT FROM v.profile_sha256
    OR (expected->>'plan_sha256') IS DISTINCT FROM v.plan_sha256
    OR (expected->>'source_id') IS DISTINCT FROM e.id::text OR (expected->>'source_sha256') IS DISTINCT FROM e.content_sha256
    OR (expected->>'audience') IS DISTINCT FROM 'synthetic-destination-publication'
    OR (expected->>'provider') IS DISTINCT FROM 'publication-simulator'
    OR (expected->>'reported') IS DISTINCT FROM (CASE WHEN NEW.action='SIMULATED_PUBLISHED' THEN 'PUBLISHED' ELSE NEW.action END)
    OR coalesce(expected->>'issuer','') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR coalesce(expected->>'key_id','') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR coalesce(expected->>'signature_b64url','') !~ '^[A-Za-z0-9_-]{86}$'
    OR coalesce(expected->>'issued_at','')='' OR coalesce(expected->>'expires_at','')=''
    OR (expected->>'issued_at')::timestamptz<prep.created_at-interval '30 seconds'
    OR (expected->>'issued_at')::timestamptz>clock_timestamp()+interval '30 seconds'
    OR (expected->>'expires_at')::timestamptz<=clock_timestamp()
    OR (expected->>'expires_at')::timestamptz>(expected->>'issued_at')::timestamptz+interval '15 minutes' THEN
    RAISE EXCEPTION 'destination signed simulator scope invalid' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER pd_version_guard BEFORE INSERT OR UPDATE OR DELETE ON publication_destinations_destinationversion FOR EACH ROW EXECUTE FUNCTION pd_history_guard();
CREATE TRIGGER pd_event_guard BEFORE INSERT OR UPDATE OR DELETE ON publication_destinations_destinationevent FOR EACH ROW EXECUTE FUNCTION pd_history_guard();
"""

# PostgreSQL has jsonb_object_keys but no jsonb_object_length on supported majors.
SQL = SQL.replace(
    "jsonb_object_length_compat(profile)", "(SELECT count(*) FROM jsonb_object_keys(profile))"
)
SQL = SQL.replace(
    "jsonb_object_length_compat(expected)", "(SELECT count(*) FROM jsonb_object_keys(expected))"
)

REVERSE = """
DROP TRIGGER pd_event_guard ON publication_destinations_destinationevent;
DROP TRIGGER pd_version_guard ON publication_destinations_destinationversion;
DROP TRIGGER pd_record_guard ON publication_destinations_destinationrecord;
DROP FUNCTION pd_history_guard(); DROP FUNCTION pd_record_guard(); DROP FUNCTION pd_source_pin(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("publication_destinations", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
