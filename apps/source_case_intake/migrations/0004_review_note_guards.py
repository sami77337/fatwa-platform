from django.db import migrations

SQL = """
CREATE FUNCTION sci_review_note_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE latest integer;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.receipt_id::text, 911));
 SELECT coalesce(max(sequence), 0) INTO latest FROM source_case_intake_sourcereviewnote
 WHERE receipt_id=NEW.receipt_id;
 IF NEW.sequence<>latest+1 OR length(NEW.text) NOT BETWEEN 1 AND 2000
    OR NEW.text !~ '\\S' OR NEW.request_key !~ '^[a-f0-9]{64}$'
    OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' THEN
  RAISE EXCEPTION 'invalid source review note' USING ERRCODE='23514';
 END IF;
 IF NEW.kind <> 'NOTE' AND (
     EXISTS (SELECT 1 FROM source_case_intake_evidencebinding WHERE receipt_id=NEW.receipt_id)
     OR NOT EXISTS (SELECT 1 FROM source_case_intake_reviewticket WHERE receipt_id=NEW.receipt_id)) THEN
  RAISE EXCEPTION 'unbound source review required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER sci_review_note_insert BEFORE INSERT ON source_case_intake_sourcereviewnote
 FOR EACH ROW EXECUTE FUNCTION sci_review_note_insert();
CREATE TRIGGER sci_review_note_immutable BEFORE UPDATE OR DELETE ON source_case_intake_sourcereviewnote
 FOR EACH ROW EXECUTE FUNCTION sci_immutable();
"""
REVERSE = """
DROP TRIGGER sci_review_note_immutable ON source_case_intake_sourcereviewnote;
DROP TRIGGER sci_review_note_insert ON source_case_intake_sourcereviewnote;
DROP FUNCTION sci_review_note_insert();
"""


class Migration(migrations.Migration):
    dependencies = [("source_case_intake", "0003_sourcereviewnote")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
