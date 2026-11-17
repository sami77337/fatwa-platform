from django.db import migrations

SQL = """
CREATE FUNCTION transcript_upload_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'transcript provenance immutable' USING ERRCODE='23514';
 END IF;
 IF octet_length(NEW.bundle) NOT BETWEEN 1 AND 192000
    OR NEW.sha256 <> encode(sha256(NEW.bundle),'hex')
    OR NEW.case_revision < 1 OR NEW.evidence_version < 1
    OR NEW.subject_id = '' OR NEW.provider_id = '' OR NEW.auth_epoch = '' THEN
  RAISE EXCEPTION 'transcript upload invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transcript_upload_guard BEFORE INSERT OR UPDATE OR DELETE
 ON transcript_case_links_transcriptupload FOR EACH ROW EXECUTE FUNCTION transcript_upload_guard();
CREATE FUNCTION transcript_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'transcript link immutable' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM transcript_case_links_transcriptupload u
  JOIN casework_caseevidence e ON e.id=NEW.evidence_id
  JOIN casework_caseevent v ON v.id=NEW.event_id
  WHERE u.id=NEW.upload_id AND u.case_id=NEW.case_id
   AND e.case_id=NEW.case_id AND v.case_id=NEW.case_id
   AND e.kind='FOLLOWUP' AND e.version=u.evidence_version+1
   AND v.evidence_version=e.version AND v.sequence=u.case_revision+1
   AND v.action='FOLLOWUP' AND v.note='TRANSCRIPT:' || NEW.id::text
   AND v.subject_id=u.subject_id AND e.text_sha256=NEW.question_sha256
 ) THEN RAISE EXCEPTION 'transcript case evidence mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER transcript_link_guard BEFORE INSERT OR UPDATE OR DELETE
 ON transcript_case_links_transcriptlink FOR EACH ROW EXECUTE FUNCTION transcript_link_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("transcript_case_links", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER transcript_link_guard ON transcript_case_links_transcriptlink;
        DROP FUNCTION transcript_link_guard();
        DROP TRIGGER transcript_upload_guard ON transcript_case_links_transcriptupload;
        DROP FUNCTION transcript_upload_guard();
    """,
        )
    ]
