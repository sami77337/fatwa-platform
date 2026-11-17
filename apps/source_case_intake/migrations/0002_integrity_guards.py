from django.db import migrations

SQL = """
CREATE FUNCTION sci_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'source intake history is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION sci_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF octet_length(NEW.raw) NOT BETWEEN 1 AND 262144
    OR encode(sha256(NEW.raw), 'hex') <> NEW.sha256
    OR NEW.source NOT IN ('telegram','youtube','website')
    OR NEW.account NOT LIKE 'synthetic-%'
    OR jsonb_typeof(NEW.attachments) <> 'array' THEN
  RAISE EXCEPTION 'invalid source receipt' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER sci_receipt_insert BEFORE INSERT ON source_case_intake_sourcereceipt
 FOR EACH ROW EXECUTE FUNCTION sci_receipt_guard();

CREATE FUNCTION sci_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r source_case_intake_sourcereceipt%ROWTYPE;
        e casework_caseevidence%ROWTYPE; requester text; origin text; attached_case uuid;
BEGIN
 SELECT * INTO r FROM source_case_intake_sourcereceipt WHERE id=NEW.receipt_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'receipt required' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='source_case_intake_evidencebinding' THEN
  SELECT * INTO e FROM casework_caseevidence WHERE id=NEW.evidence_id;
  SELECT requester_id INTO requester FROM casework_case WHERE id=NEW.case_id;
  IF e.case_id IS DISTINCT FROM NEW.case_id OR e.text IS DISTINCT FROM r.original_text
     OR requester IS DISTINCT FROM r.requester_key OR r.sender='' OR r.problem<>''
     OR NEW.message_key<>r.message_key OR NEW.action NOT IN ('CREATED','FOLLOWUP')
     OR (NEW.action='CREATED') IS DISTINCT FROM (e.version=1) THEN
   RAISE EXCEPTION 'source evidence mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.action='CREATED' THEN
   SELECT source_event_id INTO origin FROM casework_casesource WHERE case_id=NEW.case_id;
   IF origin IS DISTINCT FROM 'source:' || r.id::text THEN
    RAISE EXCEPTION 'source case mismatch' USING ERRCODE='23514';
   END IF;
  ELSIF NOT EXISTS (
   SELECT 1 FROM source_case_intake_evidencebinding b
    JOIN source_case_intake_sourcereceipt p ON p.id=b.receipt_id
    WHERE b.case_id=NEW.case_id AND p.source=r.source AND p.account=r.account
      AND p.conversation=r.conversation AND p.thread=r.thread AND p.sender=r.sender
  ) THEN
   RAISE EXCEPTION 'source identity mismatch' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM source_case_intake_reviewticket WHERE receipt_id=r.id)
     AND (NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.review_note='') THEN
   RAISE EXCEPTION 'human review audit required' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT case_id INTO attached_case FROM case_attachments_caseattachment WHERE id=NEW.attachment_id;
  IF NOT EXISTS (SELECT 1 FROM source_case_intake_evidencebinding
                 WHERE receipt_id=r.id AND case_id=attached_case)
     OR NOT r.attachments @> jsonb_build_array(jsonb_build_object('source_file_id',NEW.source_file_id)) THEN
   RAISE EXCEPTION 'source attachment mismatch' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""

TABLES = ("sourcereceipt", "reviewticket", "evidencebinding", "attachmentbinding")
for table in TABLES:
    SQL += f"""
CREATE TRIGGER sci_{table}_immutable BEFORE UPDATE OR DELETE ON source_case_intake_{table}
 FOR EACH ROW EXECUTE FUNCTION sci_immutable();
"""
for table in ("evidencebinding", "attachmentbinding"):
    SQL += f"""
CREATE TRIGGER sci_{table}_insert BEFORE INSERT ON source_case_intake_{table}
 FOR EACH ROW EXECUTE FUNCTION sci_binding_guard();
"""

REVERSE = """
DROP TRIGGER sci_receipt_insert ON source_case_intake_sourcereceipt;
DROP FUNCTION sci_receipt_guard();
"""
for table in TABLES:
    REVERSE += f"DROP TRIGGER sci_{table}_immutable ON source_case_intake_{table};\n"
for table in ("evidencebinding", "attachmentbinding"):
    REVERSE += f"DROP TRIGGER sci_{table}_insert ON source_case_intake_{table};\n"
REVERSE += "DROP FUNCTION sci_binding_guard(); DROP FUNCTION sci_immutable();"


class Migration(migrations.Migration):
    dependencies = [("source_case_intake", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
