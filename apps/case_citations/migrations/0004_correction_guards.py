from django.db import migrations

SQL = """
CREATE FUNCTION citation_correction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'citation corrections immutable' USING ERRCODE='23514';
 END IF;
 IF length(trim(NEW.reason))=0 OR length(NEW.reason)>2000 OR NOT EXISTS (
  SELECT 1 FROM case_citations_answercitation n
  JOIN casework_answerrevision a ON a.id=n.answer_id
  JOIN casework_case c ON c.id=a.case_id
  JOIN case_citations_answercitation p ON p.id=NEW.previous_id
  JOIN casework_answerrevision prior_answer ON prior_answer.id=p.answer_id
  JOIN casework_caseevent v ON v.case_id=c.id AND v.sequence=c.revision
  WHERE n.id=NEW.citation_id AND prior_answer.case_id=a.case_id
    AND prior_answer.revision=a.revision-1 AND a.revision=c.answer_revision
    AND a.created_at >= transaction_timestamp()
    AND a.evidence_version=c.evidence_version AND c.approved_answer_id IS NULL
    AND c.stage='UNDER_REVIEW' AND v.action='SAVE_ANSWER' AND v.answer_id=a.id
    AND NOT EXISTS(SELECT 1 FROM casework_casedecision d WHERE d.answer_id=a.id)
 ) OR EXISTS (
  SELECT 1 FROM case_citations_citationcorrection other
  JOIN case_citations_answercitation x ON x.id=other.citation_id
  JOIN case_citations_answercitation n ON n.answer_id=x.answer_id
  WHERE n.id=NEW.citation_id AND other.previous_id=NEW.previous_id
 ) THEN
  RAISE EXCEPTION 'citation correction lineage mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER citation_correction_guard BEFORE INSERT OR UPDATE OR DELETE
 ON case_citations_citationcorrection FOR EACH ROW EXECUTE FUNCTION citation_correction_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("case_citations", "0003_citationcorrection")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER citation_correction_guard ON case_citations_citationcorrection;
        DROP FUNCTION citation_correction_guard();
    """,
        )
    ]
