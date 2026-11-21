from django.db import migrations, models

SQL = """CREATE OR REPLACE FUNCTION composite_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
  AND m.sha256=NEW.manifest_sha256
  AND ((NEW.selection_mode='ALL' AND m.part_count=q.expected_parts)
   OR (NEW.selection_mode='TEXT_ONLY' AND q.expected_parts=1
       AND EXISTS(SELECT 1 FROM answer_media_answerpart t WHERE t.manifest_id=m.answer_id AND t.kind='TEXT' AND t.ordinal=1)
       AND EXISTS(SELECT 1 FROM answer_media_answerpart t WHERE t.manifest_id=m.answer_id AND t.kind='AUDIO')))
  AND ctx.envelope->'evidence'->>'answer_sha256'=m.sha256
  AND ctx.envelope->'receipt'->>'approver_id'=d.subject_id
  AND ctx.envelope->'plan'->>'source_provider'='composite-simulator'
 ) THEN
  RAISE EXCEPTION 'current composite signed scope required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""

REVERSE = """DO $$ BEGIN IF EXISTS(SELECT 1 FROM composite_delivery_compositedelivery WHERE selection_mode <> 'ALL') THEN RAISE EXCEPTION 'cannot remove recorded explicit delivery choices'; END IF; END $$;
CREATE OR REPLACE FUNCTION composite_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""

class Migration(migrations.Migration):
    dependencies = [("composite_delivery", "0002_binding_guards")]
    operations = [
        migrations.AddField(
            model_name="compositedelivery",
            name="selection_mode",
            field=models.CharField(default="ALL", max_length=16),
        ),
        migrations.AddConstraint(
            model_name="compositedelivery",
            constraint=models.CheckConstraint(
                condition=models.Q(selection_mode__in=["ALL", "TEXT_ONLY"]),
                name="composite_selection_kind",
            ),
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
