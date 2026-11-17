from django.db import migrations

SQL = """
CREATE FUNCTION case_attachment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'attachment original immutable' USING ERRCODE='23514';
 END IF;
 IF octet_length(NEW.original) <> NEW.size
    OR NEW.sha256 <> encode(sha256(NEW.original),'hex')
    OR NEW.size NOT BETWEEN 1 AND 65536
    OR NEW.media_type <> 'text/plain' OR NEW.source <> 'REQUESTER_UPLOAD'
    OR NEW.filename !~ '^[A-Za-z0-9][A-Za-z0-9_. -]{0,95}\\.txt$' THEN
  RAISE EXCEPTION 'attachment original invalid' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM casework_case c
  JOIN casework_caseevidence e ON e.id=NEW.evidence_id
  JOIN casework_caseevent v ON v.id=NEW.event_id
  WHERE c.id=NEW.case_id AND e.case_id=c.id AND v.case_id=c.id
   AND e.kind='FOLLOWUP' AND v.action='FOLLOWUP'
   AND e.version=v.evidence_version AND e.version=c.evidence_version
   AND v.sequence=c.revision
   AND v.note='ATTACHMENT:' || NEW.id::text
   AND v.subject_id=NEW.subject_id AND c.requester_id=NEW.subject_id
 ) THEN RAISE EXCEPTION 'attachment case evidence mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER case_attachment_guard BEFORE INSERT OR UPDATE OR DELETE
 ON case_attachments_caseattachment FOR EACH ROW EXECUTE FUNCTION case_attachment_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("case_attachments", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER case_attachment_guard ON case_attachments_caseattachment;
        DROP FUNCTION case_attachment_guard();
    """,
        )
    ]
