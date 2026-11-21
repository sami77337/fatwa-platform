"""Immutable administrative events; preserve legacy assignment digest bytes."""

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION ca_assignment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE; previous case_assignments_assignmentevent%ROWTYPE;
        total integer; expected_digest text; primary_subject text; primary_action text;
        participant_action text; participant_count integer;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'assignment history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version THEN
  RAISE EXCEPTION 'assignment canonical pins changed' USING ERRCODE='23514';
 END IF;
 SELECT count(*) INTO total FROM case_assignments_assignmentevent WHERE case_id=NEW.case_id;
 SELECT * INTO previous FROM case_assignments_assignmentevent
  WHERE case_id=NEW.case_id ORDER BY sequence DESC LIMIT 1;
 IF total>=256 OR NEW.sequence<>total+1
  OR NEW.previous_sha256<>coalesce(previous.sha256,repeat('0',64))
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.target_subject !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR (previous.id IS NOT NULL AND previous.provider_id<>NEW.provider_id)
 THEN RAISE EXCEPTION 'assignment history binding invalid' USING ERRCODE='23514'; END IF;
 SELECT target_subject,action INTO primary_subject,primary_action
  FROM case_assignments_assignmentevent WHERE case_id=NEW.case_id
   AND action IN ('CLAIM','RELEASE','TRANSFER','SET_PRIMARY','CLEAR_PRIMARY') ORDER BY sequence DESC LIMIT 1;
 IF primary_action IN ('RELEASE','CLEAR_PRIMARY') THEN primary_subject:=NULL; END IF;
 SELECT action INTO participant_action FROM case_assignments_assignmentevent
  WHERE case_id=NEW.case_id AND target_subject=NEW.target_subject
   AND action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER','REMOVE_PARTICIPANT','CLAIM','TRANSFER','SET_PRIMARY')
  ORDER BY sequence DESC LIMIT 1;
 IF (NEW.action='SET_PRIMARY' AND NEW.target_subject IS NOT DISTINCT FROM primary_subject)
  OR (NEW.action='CLEAR_PRIMARY' AND (primary_subject IS NULL OR NEW.target_subject IS DISTINCT FROM primary_subject))
  OR (NEW.action='CLAIM' AND (primary_subject IS NOT NULL OR NEW.target_subject<>NEW.subject_id))
  OR (NEW.action='RELEASE' AND (primary_subject IS DISTINCT FROM NEW.subject_id OR NEW.target_subject<>NEW.subject_id))
  OR (NEW.action='TRANSFER' AND (primary_subject IS DISTINCT FROM NEW.subject_id OR NEW.target_subject=NEW.subject_id))
  OR (NEW.action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER') AND (
      NEW.target_subject IS NOT DISTINCT FROM primary_subject
      OR (NEW.subject_id IS DISTINCT FROM primary_subject AND NEW.target_subject<>NEW.subject_id)
      OR participant_action=NEW.action))
  OR (NEW.action='REMOVE_PARTICIPANT' AND (
      coalesce(participant_action,'') NOT IN ('ADD_CONTRIBUTOR','ADD_REVIEWER')
      OR (NEW.subject_id IS DISTINCT FROM primary_subject AND NEW.target_subject<>NEW.subject_id)))
 THEN RAISE EXCEPTION 'assignment transition invalid' USING ERRCODE='23514'; END IF;
 IF NEW.action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER')
  AND coalesce(participant_action,'') NOT IN ('ADD_CONTRIBUTOR','ADD_REVIEWER') THEN
  SELECT count(*) INTO participant_count FROM (
   SELECT DISTINCT ON (target_subject) action FROM case_assignments_assignmentevent
    WHERE case_id=NEW.case_id
     AND action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER','REMOVE_PARTICIPANT','CLAIM','TRANSFER','SET_PRIMARY')
    ORDER BY target_subject,sequence DESC
  ) members WHERE action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER');
  IF participant_count>=16 THEN RAISE EXCEPTION 'assignment participant limit' USING ERRCODE='23514'; END IF;
 END IF;

 IF NEW.action IN ('SET_PRIMARY','CLEAR_PRIMARY') THEN
  IF NEW.actor_role NOT IN ('MUFTI','ORGANIZER','ORGANIZER_ADMIN')
   OR NEW.command_id IS NULL OR length(NEW.reason) NOT BETWEEN 1 AND 2000
   OR NEW.reason !~ '[^[:space:]]'
  THEN RAISE EXCEPTION 'administrative assignment provenance missing' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.actor_role<>'' OR NEW.reason<>'' OR NEW.command_id IS NOT NULL
  THEN RAISE EXCEPTION 'legacy assignment fields must remain empty' USING ERRCODE='23514'; END IF;
 END IF;
 expected_digest:=encode(sha256(convert_to(concat_ws('|',NEW.case_id::text,NEW.sequence::text,
  NEW.action,NEW.target_subject,NEW.subject_id,NEW.provider_id,NEW.auth_epoch,
  NEW.case_revision::text,NEW.evidence_version::text,NEW.previous_sha256) ||
  CASE WHEN NEW.action IN ('SET_PRIMARY','CLEAR_PRIMARY') THEN
   '|' || NEW.actor_role || '|' || encode(sha256(convert_to(NEW.reason,'UTF8')),'hex') || '|' || NEW.command_id::text
  ELSE '' END,'UTF8')),'hex');
 IF NEW.sha256<>expected_digest THEN
  RAISE EXCEPTION 'assignment digest mismatch' USING ERRCODE='23514';
 END IF;
 NEW.transaction_id:=txid_current();
 NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;

CREATE FUNCTION ca_priority_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE; previous case_assignments_priorityevent%ROWTYPE;
        total integer; expected_digest text;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'priority history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version THEN
  RAISE EXCEPTION 'priority canonical pins changed' USING ERRCODE='23514';
 END IF;
 SELECT count(*) INTO total FROM case_assignments_priorityevent WHERE case_id=NEW.case_id;
 SELECT * INTO previous FROM case_assignments_priorityevent
  WHERE case_id=NEW.case_id ORDER BY sequence DESC LIMIT 1;
 IF total>=256 OR NEW.sequence<>total+1
  OR NEW.previous_sha256<>coalesce(previous.sha256,repeat('0',64))
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR NEW.value !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR length(NEW.reason) NOT BETWEEN 1 AND 2000 OR NEW.reason !~ '[^[:space:]]'
  OR length(NEW.label) NOT BETWEEN 1 AND 128 OR NEW.label !~ '[^[:space:]]'
  OR (previous.id IS NOT NULL AND previous.provider_id<>NEW.provider_id)
  OR (previous.id IS NOT NULL AND (previous.value,previous.label,previous.rank,previous.policy_sha256)
      IS NOT DISTINCT FROM (NEW.value,NEW.label,NEW.rank,NEW.policy_sha256))
 THEN RAISE EXCEPTION 'priority history binding invalid' USING ERRCODE='23514'; END IF;
 expected_digest:=encode(sha256(convert_to(concat_ws('|',NEW.case_id::text,NEW.sequence::text,
  NEW.value,NEW.rank::text,NEW.policy_sha256,NEW.command_id::text,NEW.subject_id,
  NEW.actor_role,NEW.provider_id,NEW.auth_epoch,NEW.case_revision::text,NEW.evidence_version::text,
  NEW.previous_sha256,encode(sha256(convert_to(NEW.label,'UTF8')),'hex'),
  encode(sha256(convert_to(NEW.reason,'UTF8')),'hex')),'UTF8')),'hex');
 IF NEW.sha256<>expected_digest THEN
  RAISE EXCEPTION 'priority digest mismatch' USING ERRCODE='23514';
 END IF;
 NEW.transaction_id:=txid_current();
 NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER ca_priority_guard BEFORE INSERT OR UPDATE OR DELETE
 ON case_assignments_priorityevent FOR EACH ROW EXECUTE FUNCTION ca_priority_guard();
"""

REVERSE = r"""
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM case_assignments_assignmentevent WHERE action IN ('SET_PRIMARY','CLEAR_PRIMARY'))
 OR EXISTS (SELECT 1 FROM case_assignments_priorityevent) THEN
  RAISE EXCEPTION 'cannot downgrade populated coordination history' USING ERRCODE='23514';
 END IF;
END $$;
DROP TRIGGER ca_priority_guard ON case_assignments_priorityevent;
DROP FUNCTION ca_priority_guard();

CREATE OR REPLACE FUNCTION ca_assignment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE; previous case_assignments_assignmentevent%ROWTYPE;
        total integer; expected_digest text; primary_subject text; primary_action text;
        participant_action text; participant_count integer;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'assignment history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version THEN
  RAISE EXCEPTION 'assignment canonical pins changed' USING ERRCODE='23514';
 END IF;
 SELECT count(*) INTO total FROM case_assignments_assignmentevent WHERE case_id=NEW.case_id;
 SELECT * INTO previous FROM case_assignments_assignmentevent
  WHERE case_id=NEW.case_id ORDER BY sequence DESC LIMIT 1;
 IF total>=256 OR NEW.sequence<>total+1
  OR NEW.previous_sha256<>coalesce(previous.sha256,repeat('0',64))
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.target_subject !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR (previous.id IS NOT NULL AND previous.provider_id<>NEW.provider_id)
 THEN RAISE EXCEPTION 'assignment history binding invalid' USING ERRCODE='23514'; END IF;
 SELECT target_subject,action INTO primary_subject,primary_action
  FROM case_assignments_assignmentevent WHERE case_id=NEW.case_id
   AND action IN ('CLAIM','RELEASE','TRANSFER') ORDER BY sequence DESC LIMIT 1;
 IF primary_action='RELEASE' THEN primary_subject:=NULL; END IF;
 SELECT action INTO participant_action FROM case_assignments_assignmentevent
  WHERE case_id=NEW.case_id AND target_subject=NEW.target_subject
   AND action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER','REMOVE_PARTICIPANT','CLAIM','TRANSFER')
  ORDER BY sequence DESC LIMIT 1;
 IF (NEW.action='CLAIM' AND (primary_subject IS NOT NULL OR NEW.target_subject<>NEW.subject_id))
  OR (NEW.action='RELEASE' AND (primary_subject IS DISTINCT FROM NEW.subject_id OR NEW.target_subject<>NEW.subject_id))
  OR (NEW.action='TRANSFER' AND (primary_subject IS DISTINCT FROM NEW.subject_id OR NEW.target_subject=NEW.subject_id))
  OR (NEW.action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER') AND (
      NEW.target_subject IS NOT DISTINCT FROM primary_subject
      OR (NEW.subject_id IS DISTINCT FROM primary_subject AND NEW.target_subject<>NEW.subject_id)
      OR participant_action=NEW.action))
  OR (NEW.action='REMOVE_PARTICIPANT' AND (
      coalesce(participant_action,'') NOT IN ('ADD_CONTRIBUTOR','ADD_REVIEWER')
      OR (NEW.subject_id IS DISTINCT FROM primary_subject AND NEW.target_subject<>NEW.subject_id)))
 THEN RAISE EXCEPTION 'assignment transition invalid' USING ERRCODE='23514'; END IF;
 IF NEW.action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER')
  AND coalesce(participant_action,'') NOT IN ('ADD_CONTRIBUTOR','ADD_REVIEWER') THEN
  SELECT count(*) INTO participant_count FROM (
   SELECT DISTINCT ON (target_subject) action FROM case_assignments_assignmentevent
    WHERE case_id=NEW.case_id
     AND action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER','REMOVE_PARTICIPANT','CLAIM','TRANSFER')
    ORDER BY target_subject,sequence DESC
  ) members WHERE action IN ('ADD_CONTRIBUTOR','ADD_REVIEWER');
  IF participant_count>=16 THEN RAISE EXCEPTION 'assignment participant limit' USING ERRCODE='23514'; END IF;
 END IF;
 expected_digest:=encode(sha256(convert_to(concat_ws('|',NEW.case_id::text,NEW.sequence::text,
  NEW.action,NEW.target_subject,NEW.subject_id,NEW.provider_id,NEW.auth_epoch,
  NEW.case_revision::text,NEW.evidence_version::text,NEW.previous_sha256),'UTF8')),'hex');
 IF NEW.sha256<>expected_digest THEN
  RAISE EXCEPTION 'assignment digest mismatch' USING ERRCODE='23514';
 END IF;
 NEW.transaction_id:=txid_current();
 NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("case_assignments", "0003_administrative_coordination")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
