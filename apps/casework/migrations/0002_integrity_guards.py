"""PostgreSQL immutable provenance and cross-case relational guards.

No legacy rows are imported or rewritten. Only the new casework tables change.
"""

from django.db import migrations

SQL = r"""
ALTER TABLE casework_answerrevision ADD CONSTRAINT cw_answer_evidence_fk
 FOREIGN KEY (case_id, evidence_version) REFERENCES casework_caseevidence(case_id, version)
 DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION cw_immutable_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'immutable case history' USING ERRCODE='23514';
END $$;
CREATE FUNCTION cw_case_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'case deletion forbidden' USING ERRCODE='23514';
 END IF;
 IF TG_OP = 'UPDATE' AND (
  NEW.id IS DISTINCT FROM OLD.id OR NEW.public_ref IS DISTINCT FROM OLD.public_ref
  OR NEW.requester_id IS DISTINCT FROM OLD.requester_id
  OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
  OR NEW.intake_sha256 IS DISTINCT FROM OLD.intake_sha256
  OR NEW.tracking_id IS DISTINCT FROM OLD.tracking_id
  OR NEW.created_at IS DISTINCT FROM OLD.created_at
  OR NEW.revision <> OLD.revision + 1
 ) THEN
  RAISE EXCEPTION 'case identity immutable or invalid revision' USING ERRCODE='23514';
 END IF;
 IF NEW.tracking_id <> 'case:' || NEW.id::text THEN
  RAISE EXCEPTION 'case tracking mismatch' USING ERRCODE='23514';
 END IF;
 IF NEW.approved_answer_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM casework_answerrevision a JOIN casework_casedecision d ON d.answer_id=a.id
  WHERE a.id=NEW.approved_answer_id AND a.case_id=NEW.id AND d.case_id=NEW.id
  AND a.evidence_version=NEW.evidence_version AND a.revision=NEW.answer_revision
  AND d.evidence_version=NEW.evidence_version AND d.action='APPROVE'
 ) THEN
  RAISE EXCEPTION 'current scoped approval required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cw_case_identity BEFORE INSERT OR UPDATE OR DELETE ON casework_case
 FOR EACH ROW EXECUTE FUNCTION cw_case_identity_guard();
CREATE FUNCTION cw_case_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a_case uuid; a_version integer; d_case uuid; d_answer uuid;
BEGIN
 IF TG_TABLE_NAME IN ('casework_casesource','casework_caseevidence','casework_answerrevision') THEN
  IF TG_TABLE_NAME = 'casework_casesource' THEN
   IF NEW.question_sha256 <> encode(sha256(convert_to(NEW.original_question,'UTF8')),'hex')
      OR length(NEW.original_question) NOT BETWEEN 1 AND 16000 THEN
    RAISE EXCEPTION 'source digest mismatch' USING ERRCODE='23514';
   END IF;
  ELSE
   IF NEW.text_sha256 <> encode(sha256(convert_to(NEW.text,'UTF8')),'hex')
      OR length(NEW.text) NOT BETWEEN 1 AND 16000 OR NEW.text !~ '\S' THEN
    RAISE EXCEPTION 'text digest mismatch' USING ERRCODE='23514';
   END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME = 'casework_casedecision' THEN
  SELECT case_id, evidence_version INTO a_case, a_version FROM casework_answerrevision WHERE id=NEW.answer_id;
  IF a_case IS DISTINCT FROM NEW.case_id OR a_version IS DISTINCT FROM NEW.evidence_version THEN
   RAISE EXCEPTION 'decision case or evidence mismatch' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_TABLE_NAME = 'casework_caseevent' THEN
  IF NEW.answer_id IS NOT NULL THEN
   SELECT case_id INTO a_case FROM casework_answerrevision WHERE id=NEW.answer_id;
   IF a_case IS DISTINCT FROM NEW.case_id THEN
    RAISE EXCEPTION 'event answer case mismatch' USING ERRCODE='23514';
   END IF;
  END IF;
  IF NEW.decision_id IS NOT NULL THEN
   SELECT case_id, answer_id INTO d_case, d_answer FROM casework_casedecision WHERE id=NEW.decision_id;
   IF d_case IS DISTINCT FROM NEW.case_id OR d_answer IS DISTINCT FROM NEW.answer_id THEN
    RAISE EXCEPTION 'event decision mismatch' USING ERRCODE='23514';
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cw_case_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cid uuid; c casework_case%ROWTYPE; last_event casework_caseevent%ROWTYPE;
        total integer; highest integer; original text;
BEGIN
 IF TG_TABLE_NAME='casework_case' THEN cid:=NEW.id; ELSE cid:=NEW.case_id; END IF;
 SELECT * INTO c FROM casework_case WHERE id=cid;
 IF NOT FOUND THEN RAISE EXCEPTION 'orphan case child' USING ERRCODE='23514'; END IF;
 SELECT original_question INTO original FROM casework_casesource WHERE case_id=cid;
 IF NOT FOUND THEN RAISE EXCEPTION 'case source required' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS (SELECT 1 FROM casework_caseevidence WHERE case_id=cid AND version=1
                AND kind='ORIGINAL' AND text=original) THEN
  RAISE EXCEPTION 'case original evidence mismatch' USING ERRCODE='23514';
 END IF;
 SELECT count(*), max(version) INTO total, highest FROM casework_caseevidence WHERE case_id=cid;
 IF total <> c.evidence_version OR highest <> c.evidence_version THEN
  RAISE EXCEPTION 'case evidence head mismatch' USING ERRCODE='23514';
 END IF;
 SELECT count(*), coalesce(max(revision),0) INTO total, highest FROM casework_answerrevision WHERE case_id=cid;
 IF total <> c.answer_revision OR highest <> c.answer_revision THEN
  RAISE EXCEPTION 'case answer head mismatch' USING ERRCODE='23514';
 END IF;
 SELECT count(*), max(sequence) INTO total, highest FROM casework_caseevent WHERE case_id=cid;
 IF total <> c.revision OR highest <> c.revision THEN
  RAISE EXCEPTION 'case history head mismatch' USING ERRCODE='23514';
 END IF;
 IF EXISTS (
  SELECT 1 FROM casework_casedecision d WHERE d.case_id=cid AND NOT EXISTS (
   SELECT 1 FROM casework_caseevent e WHERE e.case_id=cid AND e.decision_id=d.id
    AND e.answer_id=d.answer_id AND e.action=d.action AND e.evidence_version=d.evidence_version
  )
 ) THEN
  RAISE EXCEPTION 'case decision event required' USING ERRCODE='23514';
 END IF;
 SELECT * INTO last_event FROM casework_caseevent WHERE case_id=cid ORDER BY sequence DESC LIMIT 1;
 IF last_event.stage <> c.stage OR last_event.evidence_version <> c.evidence_version
    OR last_event.answer_revision <> c.answer_revision THEN
  RAISE EXCEPTION 'case history state mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
"""
for table in (
    "casework_casesource",
    "casework_caseevidence",
    "casework_answerrevision",
    "casework_casedecision",
    "casework_caseevent",
):
    SQL += f"""
CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
 FOR EACH ROW EXECUTE FUNCTION cw_immutable_history();
CREATE TRIGGER {table}_child_guard BEFORE INSERT ON {table}
 FOR EACH ROW EXECUTE FUNCTION cw_case_child_guard();
CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON {table}
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cw_case_complete();
"""
SQL += """
CREATE CONSTRAINT TRIGGER casework_case_complete AFTER INSERT OR UPDATE ON casework_case
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cw_case_complete();
"""

REVERSE = """
DROP TRIGGER casework_case_complete ON casework_case;
DROP TRIGGER cw_case_identity ON casework_case;
"""
for table in (
    "casework_casesource",
    "casework_caseevidence",
    "casework_answerrevision",
    "casework_casedecision",
    "casework_caseevent",
):
    REVERSE += f"""
DROP TRIGGER {table}_immutable ON {table};
DROP TRIGGER {table}_child_guard ON {table};
DROP TRIGGER {table}_complete ON {table};
"""
REVERSE += """
DROP FUNCTION cw_case_complete();
DROP FUNCTION cw_case_child_guard();
DROP FUNCTION cw_case_identity_guard();
DROP FUNCTION cw_immutable_history();
ALTER TABLE casework_answerrevision DROP CONSTRAINT cw_answer_evidence_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("casework", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
