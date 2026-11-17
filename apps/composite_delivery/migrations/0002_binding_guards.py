"""Immutable canonical decision/manifest/queue scope; no second outbox."""

from django.db import migrations

SQL = """
CREATE TRIGGER composite_binding_immutable
 BEFORE UPDATE OR DELETE ON composite_delivery_compositedelivery
 FOR EACH ROW EXECUTE FUNCTION cw_immutable_history();
CREATE FUNCTION composite_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.capability_sha256 !~ '^[a-f0-9]{64}$' OR NOT EXISTS (
  SELECT 1 FROM casework_casedecision d
  JOIN casework_case c ON c.id=d.case_id
  JOIN casework_answerrevision a ON a.id=d.answer_id
  JOIN answer_media_answermanifest m ON m.answer_id=a.id
  JOIN fatwa_delivery_approval_claim q ON q.receipt_id=NEW.approval_id
  JOIN fatwa_delivery_signed_context ctx ON ctx.approval_id=q.receipt_id
  WHERE d.id=NEW.decision_id AND d.action='APPROVE'
  AND c.stage='ANSWERED' AND c.approved_answer_id=a.id
  AND d.evidence_version=c.evidence_version AND a.evidence_version=c.evidence_version
  AND a.revision=c.answer_revision AND q.answer_revision=a.revision AND q.case_key=c.public_ref
  AND m.sha256=NEW.manifest_sha256 AND m.part_count=q.expected_parts
  AND ctx.envelope->'evidence'->>'answer_sha256'=m.sha256
  AND ctx.envelope->'receipt'->>'approver_id'=d.subject_id
  AND ctx.envelope->'plan'->>'source_provider'='composite-simulator'
 ) THEN
  RAISE EXCEPTION 'current composite signed scope required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER composite_binding_scope BEFORE INSERT ON composite_delivery_compositedelivery
 FOR EACH ROW EXECUTE FUNCTION composite_binding_guard();
"""
REVERSE = """
DROP TRIGGER composite_binding_scope ON composite_delivery_compositedelivery;
DROP FUNCTION composite_binding_guard();
DROP TRIGGER composite_binding_immutable ON composite_delivery_compositedelivery;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("composite_delivery", "0001_initial"),
        ("answer_media", "0003_media_metadata_guards"),
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
