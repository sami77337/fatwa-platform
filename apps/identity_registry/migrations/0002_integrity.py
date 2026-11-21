from django.db import migrations

SQL = r"""
CREATE FUNCTION identity_registry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p identity_registry_platformidentity%ROWTYPE; m identity_registry_identitymembership%ROWTYPE;
 q identity_registry_linkproposal%ROWTYPE; o identity_registry_registryoperation%ROWTYPE;
 c casework_case%ROWTYPE; s casework_casesource%ROWTYPE; r source_case_intake_sourcereceipt%ROWTYPE;
 item jsonb; prior text; current_person uuid; n integer; total integer; matched boolean;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'identity history immutable' USING ERRCODE='23514'; END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
 THEN RAISE EXCEPTION 'identity seal invalid' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 IF TG_TABLE_NAME='identity_registry_platformidentity' THEN
  IF btrim(NEW.account)='' OR btrim(NEW.source_subject)='' OR NEW.identity_key !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'platform identity invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='identity_registry_identityobservation' THEN
  SELECT * INTO p FROM identity_registry_platformidentity WHERE id=NEW.identity_id;
  SELECT * INTO c FROM casework_case WHERE id=NEW.case_id;
  SELECT * INTO s FROM casework_casesource WHERE case_id=c.id;
  IF NEW.origin_digest !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'origin digest invalid' USING ERRCODE='23514'; END IF;
  IF left(s.source_event_id,7)='source:' THEN
   SELECT x.* INTO r FROM source_case_intake_sourcereceipt x
    JOIN source_case_intake_evidencebinding b ON b.receipt_id=x.id
    JOIN casework_caseevidence e ON e.id=b.evidence_id
    WHERE b.case_id=c.id AND e.version=1 AND b.action='CREATED' AND x.id=NEW.receipt_id;
   IF r.id IS NULL OR s.source_event_id<>'source:'||r.id::text OR r.sender='' OR
    p.source<>r.source OR p.account<>r.account OR p.source_subject<>r.sender OR NEW.display_name<>r.display_name
    OR r.requester_key<>c.requester_id OR r.original_text<>s.original_question OR r.sha256<>encode(sha256(r.raw),'hex')
   THEN RAISE EXCEPTION 'bound source identity required' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.receipt_id IS NOT NULL OR p.source<>'WEBSITE_SESSION' OR p.account<>'native-casework'
    OR p.source_subject<>c.requester_id OR NEW.display_name<>''
   THEN RAISE EXCEPTION 'website session identity invalid' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='identity_registry_person' THEN
  IF btrim(NEW.label)='' OR btrim(NEW.reason)='' THEN RAISE EXCEPTION 'person purpose required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='identity_registry_linkproposal' THEN
  SELECT * INTO m FROM identity_registry_identitymembership WHERE identity_id=NEW.identity_id ORDER BY sequence DESC LIMIT 1;
  IF NEW.previous_digest<>coalesce(m.digest,repeat('0',64)) OR m.person_id IS NOT NULL OR btrim(NEW.evidence)=''
   OR EXISTS(SELECT 1 FROM identity_registry_linkproposal x LEFT JOIN identity_registry_registryoperation d ON d.proposal_id=x.id WHERE x.identity_id=NEW.identity_id AND d.id IS NULL)
  THEN RAISE EXCEPTION 'unlinked exact proposal required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='identity_registry_registryoperation' THEN
  IF jsonb_typeof(NEW.changes) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.changes)>64
   OR btrim(NEW.reason)='' OR NEW.preview_digest !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'identity operation invalid' USING ERRCODE='23514'; END IF;
  n:=jsonb_array_length(NEW.changes);
  IF NEW.kind IN ('VERIFY','REJECT') THEN
   SELECT * INTO q FROM identity_registry_linkproposal WHERE id=NEW.proposal_id;
   SELECT * INTO m FROM identity_registry_identitymembership WHERE identity_id=q.identity_id ORDER BY sequence DESC LIMIT 1;
   IF q.id IS NULL OR NEW.target_person_id IS DISTINCT FROM q.person_id OR NEW.source_person_id IS NOT NULL
    OR (NEW.provider_id=q.provider_id AND NEW.subject_id=q.subject_id)
    OR q.previous_digest<>coalesce(m.digest,repeat('0',64)) OR m.person_id IS NOT NULL
    OR (NEW.kind='VERIFY' AND n<>1) OR (NEW.kind='REJECT' AND n<>0)
   THEN RAISE EXCEPTION 'independent current verification required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.proposal_id IS NOT NULL THEN RAISE EXCEPTION 'unexpected identity proposal' USING ERRCODE='23514';
  END IF;
  IF NEW.kind='UNLINK' AND (n<>1 OR NEW.source_person_id IS NOT NULL OR NEW.target_person_id IS NOT NULL)
  THEN RAISE EXCEPTION 'unlink shape invalid' USING ERRCODE='23514'; END IF;
  IF NEW.kind IN ('MERGE','SPLIT') THEN
   IF NEW.source_person_id IS NULL OR NEW.target_person_id IS NULL OR NEW.source_person_id=NEW.target_person_id OR n=0
    OR NEW.preview_digest=repeat('0',64) THEN RAISE EXCEPTION 'identity group preview required' USING ERRCODE='23514'; END IF;
   SELECT count(*) INTO total FROM identity_registry_identitymembership x WHERE x.person_id=NEW.source_person_id
     AND NOT EXISTS(SELECT 1 FROM identity_registry_identitymembership z WHERE z.identity_id=x.identity_id AND z.sequence>x.sequence);
   IF (NEW.kind='MERGE' AND n<>total) OR (NEW.kind='SPLIT' AND n>=total)
   THEN RAISE EXCEPTION 'identity group selection invalid' USING ERRCODE='23514'; END IF;
  END IF;
  IF (SELECT count(DISTINCT x->>'identity_id') FROM jsonb_array_elements(NEW.changes) x)<>n
  THEN RAISE EXCEPTION 'identity operation duplicate member' USING ERRCODE='23514'; END IF;
  FOR item IN SELECT * FROM jsonb_array_elements(NEW.changes) LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR NOT item ?& ARRAY['identity_id','before_digest','before_person','after_person','sequence']
    OR (SELECT count(*) FROM jsonb_object_keys(item))<>5 THEN RAISE EXCEPTION 'identity change invalid' USING ERRCODE='23514'; END IF;
   SELECT * INTO m FROM identity_registry_identitymembership WHERE identity_id=(item->>'identity_id')::uuid ORDER BY sequence DESC LIMIT 1;
   IF item->>'before_digest'<>coalesce(m.digest,repeat('0',64)) OR (item->>'before_person')::uuid IS DISTINCT FROM m.person_id
    OR (item->>'sequence')::integer<>coalesce(m.sequence,0)+1
   THEN RAISE EXCEPTION 'identity membership changed' USING ERRCODE='23514'; END IF;
   IF NEW.kind='VERIFY' THEN
    IF (item->>'identity_id')::uuid<>q.identity_id OR (item->>'after_person')::uuid IS DISTINCT FROM q.person_id
    THEN RAISE EXCEPTION 'identity verification target mismatch' USING ERRCODE='23514'; END IF;
   ELSIF NEW.kind='UNLINK' THEN
    IF m.person_id IS NULL OR item->>'after_person' IS NOT NULL THEN RAISE EXCEPTION 'verified unlink required' USING ERRCODE='23514'; END IF;
   ELSE
    IF m.person_id IS DISTINCT FROM NEW.source_person_id OR (item->>'after_person')::uuid IS DISTINCT FROM NEW.target_person_id
    THEN RAISE EXCEPTION 'identity merge split mismatch' USING ERRCODE='23514'; END IF;
   END IF;
  END LOOP;
 ELSE
  SELECT * INTO o FROM identity_registry_registryoperation WHERE id=NEW.operation_id;
  SELECT * INTO m FROM identity_registry_identitymembership WHERE identity_id=NEW.identity_id ORDER BY sequence DESC LIMIT 1;
  SELECT EXISTS(SELECT 1 FROM jsonb_array_elements(o.changes) x WHERE (x->>'identity_id')::uuid=NEW.identity_id
   AND (x->>'sequence')::integer=NEW.sequence AND x->>'before_digest'=NEW.previous_digest
   AND (x->>'after_person')::uuid IS NOT DISTINCT FROM NEW.person_id) INTO matched;
  IF NOT matched OR NEW.sequence<>coalesce(m.sequence,0)+1 OR NEW.previous_digest<>coalesce(m.digest,repeat('0',64))
   OR NEW.provider_id<>o.provider_id OR NEW.subject_id<>o.subject_id OR NEW.auth_epoch<>o.auth_epoch
  THEN RAISE EXCEPTION 'identity operation membership mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER ir_identity_guard BEFORE INSERT OR UPDATE OR DELETE ON identity_registry_platformidentity FOR EACH ROW EXECUTE FUNCTION identity_registry_guard();
CREATE TRIGGER ir_observation_guard BEFORE INSERT OR UPDATE OR DELETE ON identity_registry_identityobservation FOR EACH ROW EXECUTE FUNCTION identity_registry_guard();
CREATE TRIGGER ir_person_guard BEFORE INSERT OR UPDATE OR DELETE ON identity_registry_person FOR EACH ROW EXECUTE FUNCTION identity_registry_guard();
CREATE TRIGGER ir_proposal_guard BEFORE INSERT OR UPDATE OR DELETE ON identity_registry_linkproposal FOR EACH ROW EXECUTE FUNCTION identity_registry_guard();
CREATE TRIGGER ir_operation_guard BEFORE INSERT OR UPDATE OR DELETE ON identity_registry_registryoperation FOR EACH ROW EXECUTE FUNCTION identity_registry_guard();
CREATE TRIGGER ir_membership_guard BEFORE INSERT OR UPDATE OR DELETE ON identity_registry_identitymembership FOR EACH ROW EXECUTE FUNCTION identity_registry_guard();
CREATE FUNCTION identity_registry_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM identity_registry_identitymembership WHERE operation_id=NEW.id)<>jsonb_array_length(NEW.changes)
 THEN RAISE EXCEPTION 'identity operation incomplete' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER ir_operation_complete AFTER INSERT ON identity_registry_registryoperation DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION identity_registry_complete();
"""

REVERSE = """
DROP TRIGGER ir_operation_complete ON identity_registry_registryoperation;
DROP FUNCTION identity_registry_complete();
DROP TRIGGER ir_membership_guard ON identity_registry_identitymembership;
DROP TRIGGER ir_operation_guard ON identity_registry_registryoperation;
DROP TRIGGER ir_proposal_guard ON identity_registry_linkproposal;
DROP TRIGGER ir_person_guard ON identity_registry_person;
DROP TRIGGER ir_observation_guard ON identity_registry_identityobservation;
DROP TRIGGER ir_identity_guard ON identity_registry_platformidentity;
DROP FUNCTION identity_registry_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("identity_registry", "0001_initial"),
        ("source_case_intake", "0002_integrity_guards"),
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
