"""Immutable bridge; preserve existing cases and queue receipts unchanged."""

from django.db import migrations

SQL = """
CREATE TRIGGER cw_delivery_immutable BEFORE UPDATE OR DELETE ON casework_casedelivery
 FOR EACH ROW EXECUTE FUNCTION cw_immutable_history();
CREATE FUNCTION cw_delivery_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM casework_casedecision d
  JOIN casework_case c ON c.id=d.case_id
  JOIN casework_answerrevision a ON a.id=d.answer_id
  JOIN fatwa_delivery_approval_claim q ON q.receipt_id=NEW.approval_id
  JOIN fatwa_delivery_signed_context ctx ON ctx.approval_id=q.receipt_id
  WHERE d.id=NEW.decision_id AND d.action='APPROVE'
  AND c.stage='ANSWERED' AND c.approved_answer_id=a.id
  AND d.evidence_version=c.evidence_version AND a.evidence_version=c.evidence_version
  AND a.revision=c.answer_revision AND q.answer_revision=a.revision AND q.case_key=c.public_ref
  AND ctx.envelope->'receipt'->>'approver_id'=d.subject_id
 ) THEN
  RAISE EXCEPTION 'current case signed delivery scope required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cw_delivery_scope BEFORE INSERT ON casework_casedelivery
 FOR EACH ROW EXECUTE FUNCTION cw_delivery_scope_guard();
"""

REVERSE = """
DROP TRIGGER cw_delivery_scope ON casework_casedelivery;
DROP FUNCTION cw_delivery_scope_guard();
DROP TRIGGER cw_delivery_immutable ON casework_casedelivery;
"""


class Migration(migrations.Migration):
    dependencies = [("casework", "0003_case_delivery")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
