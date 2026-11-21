from django.db import migrations

SQL = r"""
CREATE FUNCTION lifecycle_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE;
        previous case_lifecycle_lifecycleevent%ROWTYPE;
        source_event casework_caseevent%ROWTYPE;
        expected_state text;
        prior_state text;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'lifecycle history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'lifecycle case unavailable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO previous FROM case_lifecycle_lifecycleevent
  WHERE case_id=NEW.case_id ORDER BY version DESC LIMIT 1;
 prior_state := COALESCE(previous.state,'OPEN');
 expected_state := CASE
  WHEN prior_state='OPEN' AND NEW.action='CLOSE' THEN 'CLOSED'
  WHEN prior_state='CLOSED' AND NEW.action IN ('REOPEN','FOLLOWUP') THEN 'OPEN'
  WHEN prior_state='CLOSED' AND NEW.action='ARCHIVE' THEN 'ARCHIVED'
  WHEN prior_state='ARCHIVED' AND NEW.action='RESTORE' THEN 'CLOSED'
  WHEN prior_state='ARCHIVED' AND NEW.action='FOLLOWUP' THEN 'OPEN'
  ELSE NULL END;
 IF expected_state IS NULL OR NEW.version <> COALESCE(previous.version,0)+1
  OR NEW.before_state IS DISTINCT FROM prior_state OR NEW.state IS DISTINCT FROM expected_state
  OR NEW.previous_sha256 IS DISTINCT FROM COALESCE(previous.sha256,repeat('0',64))
  OR NEW.case_revision <> c.revision OR NEW.evidence_version <> c.evidence_version
  OR NEW.answer_id IS DISTINCT FROM c.approved_answer_id
  OR length(NEW.reason) NOT BETWEEN 1 AND 1000 OR NEW.reason !~ '\S'
  OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.policy_epoch=''
  OR jsonb_typeof(NEW.context) <> 'object' THEN
  RAISE EXCEPTION 'lifecycle transition or pins invalid' USING ERRCODE='23514';
 END IF;
 IF NEW.action='CLOSE' AND (
  c.stage <> 'ANSWERED' OR c.approved_answer_id IS NULL
  OR NOT EXISTS(SELECT 1 FROM casework_answerrevision a JOIN casework_casedecision d ON d.answer_id=a.id
   WHERE a.id=c.approved_answer_id AND a.case_id=c.id AND a.revision=c.answer_revision
    AND a.evidence_version=c.evidence_version AND d.case_id=c.id
    AND d.evidence_version=c.evidence_version AND d.action='APPROVE')
 ) THEN
  RAISE EXCEPTION 'lifecycle current approval required' USING ERRCODE='23514';
 END IF;
 IF NEW.actor_kind='REQUESTER_EVENT' THEN
  SELECT * INTO source_event FROM casework_caseevent WHERE id=NEW.canonical_event_id;
  IF NOT FOUND OR NEW.action <> 'FOLLOWUP' OR source_event.case_id <> c.id
   OR source_event.action <> 'FOLLOWUP' OR source_event.sequence <> c.revision
   OR source_event.evidence_version <> c.evidence_version
   OR source_event.subject_id <> c.requester_id OR NEW.subject_id <> c.requester_id
   OR c.stage <> 'UNDER_REVIEW' OR c.approved_answer_id IS NOT NULL
   OR NEW.provider_id <> 'casework-followup' OR NEW.auth_epoch <> 'canonical-event'
   OR NEW.policy_epoch <> 'canonical-event' THEN
   RAISE EXCEPTION 'lifecycle followup source invalid' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.actor_kind <> 'STAFF' OR NEW.action='FOLLOWUP' OR NEW.canonical_event_id IS NOT NULL THEN
  RAISE EXCEPTION 'lifecycle actor invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER lifecycle_event_guard BEFORE INSERT OR UPDATE OR DELETE
ON case_lifecycle_lifecycleevent FOR EACH ROW EXECUTE FUNCTION lifecycle_event_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("case_lifecycle", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER lifecycle_event_guard ON case_lifecycle_lifecycleevent; "
            "DROP FUNCTION lifecycle_event_guard();",
        )
    ]
