from django.db import migrations

SQL = """
CREATE FUNCTION experimental_publication_edition_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'publication editions immutable' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT EXISTS (
  SELECT 1 FROM casework_case c
  JOIN casework_answerrevision a ON a.id=NEW.answer_id
  JOIN casework_casedecision d ON d.id=NEW.decision_id
  WHERE c.id=NEW.case_id AND a.case_id=c.id AND d.case_id=c.id
   AND d.answer_id=a.id AND d.action='APPROVE' AND c.approved_answer_id=a.id
   AND c.stage='ANSWERED' AND c.evidence_version=NEW.evidence_version
   AND a.evidence_version=NEW.evidence_version AND d.evidence_version=NEW.evidence_version
 ) OR NEW.number <> (SELECT count(*)+1 FROM experimental_publication_publicationedition
                     WHERE case_id=NEW.case_id)
   OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
   OR NEW.title !~ '\\S' OR NEW.category !~ '\\S' OR NEW.body !~ '\\S'
   OR length(NEW.body)>16000 OR jsonb_typeof(NEW.citations)<>'array'
   OR NEW.content_sha256 !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'publication source invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER experimental_publication_edition_guard BEFORE INSERT OR UPDATE OR DELETE
 ON experimental_publication_publicationedition FOR EACH ROW
 EXECUTE FUNCTION experimental_publication_edition_guard();
CREATE FUNCTION experimental_publication_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e experimental_publication_publicationedition%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'publication actions immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=NEW.edition_id;
 PERFORM 1 FROM casework_case WHERE id=e.case_id FOR UPDATE;
 IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction
            WHERE edition_id=e.id AND action='WITHDRAW') THEN
  RAISE EXCEPTION 'publication action invalid' USING ERRCODE='23514';
 END IF;
 IF NEW.action <> 'WITHDRAW' AND (
  NOT EXISTS (SELECT 1 FROM casework_case WHERE id=e.case_id AND stage='ANSWERED'
              AND approved_answer_id=e.answer_id AND evidence_version=e.evidence_version)
  OR e.number <> (SELECT max(number) FROM experimental_publication_publicationedition
                 WHERE case_id=e.case_id)
 ) THEN RAISE EXCEPTION 'publication source changed' USING ERRCODE='23514'; END IF;
 IF NEW.action='REVIEW' AND EXISTS (
  SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id
 ) THEN RAISE EXCEPTION 'publication already reviewed' USING ERRCODE='23514'; END IF;
 IF NEW.action='APPROVE' AND (
  NOT EXISTS (SELECT 1 FROM experimental_publication_publicationaction
              WHERE edition_id=e.id AND action='REVIEW')
  OR (NEW.subject_id=e.subject_id AND NEW.provider_id=e.provider_id)
  OR EXISTS (SELECT 1 FROM casework_casedecision d WHERE d.id=e.decision_id
             AND d.subject_id=NEW.subject_id AND d.provider_id=NEW.provider_id)
  OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction
             WHERE edition_id=e.id AND action='REVIEW'
              AND subject_id=NEW.subject_id AND provider_id=NEW.provider_id)
 ) THEN RAISE EXCEPTION 'independent publication approval required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER experimental_publication_action_guard BEFORE INSERT OR UPDATE OR DELETE
 ON experimental_publication_publicationaction FOR EACH ROW
 EXECUTE FUNCTION experimental_publication_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("experimental_publication", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER experimental_publication_action_guard ON experimental_publication_publicationaction;
        DROP FUNCTION experimental_publication_action_guard();
        DROP TRIGGER experimental_publication_edition_guard ON experimental_publication_publicationedition;
        DROP FUNCTION experimental_publication_edition_guard();
    """,
        )
    ]
