"""Retain failed attempts and bind each bounded successor to signed evidence."""

from django.db import migrations

SQL = """
CREATE FUNCTION composite_retry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous composite_delivery_compositeretry;
BEGIN
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM NEW.scope
 OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex') <> NEW.sha256
 OR NEW.scope->>'schema' IS DISTINCT FROM 'fatwa.composite-retry.v1'
 OR NEW.scope->>'request_id' IS DISTINCT FROM NEW.id::text
 OR NEW.scope->>'parent_intent' IS DISTINCT FROM NEW.parent_intent_id
 OR (NEW.scope->>'logical_ordinal')::integer IS DISTINCT FROM NEW.logical_ordinal::integer
 OR (NEW.scope->>'queue_ordinal')::integer IS DISTINCT FROM 1
 OR (NEW.scope->>'retry_number')::integer IS DISTINCT FROM NEW.retry_number::integer
 OR (NEW.scope->>'max_retries')::integer IS DISTINCT FROM 3
 OR NEW.scope->'part'->>'id' IS DISTINCT FROM NEW.part_id::text
 OR NEW.scope->>'failure_evidence' IS DISTINCT FROM NEW.failure_evidence_id
 OR (SELECT count(*) FROM jsonb_object_keys(NEW.scope)) <> 19 THEN
  RAISE EXCEPTION 'exact bounded retry scope required' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM fatwa_delivery_intent WHERE intent_key=NEW.parent_intent_id FOR UPDATE;
 IF NOT EXISTS (
  SELECT 1 FROM composite_delivery_compositedelivery b
  JOIN casework_casedecision d ON d.id=b.decision_id
  JOIN casework_case c ON c.id=d.case_id
  JOIN casework_answerrevision a ON a.id=d.answer_id
  JOIN answer_media_answermanifest m ON m.answer_id=a.id
  JOIN answer_media_answerpart p ON p.id=NEW.part_id AND p.manifest_id=m.answer_id
  JOIN fatwa_delivery_approval_claim original ON original.receipt_id=b.approval_id
  JOIN fatwa_delivery_signed_context original_ctx ON original_ctx.approval_id=original.receipt_id
  JOIN fatwa_delivery_intent parent ON parent.intent_key=NEW.parent_intent_id
  JOIN fatwa_delivery_provider_receipt failure ON failure.intent_id=parent.intent_key
  JOIN fatwa_delivery_provider_signature_evidence proof ON proof.receipt_id=failure.receipt_reference
  JOIN fatwa_delivery_approval_claim child ON child.receipt_id=NEW.approval_id
  JOIN fatwa_delivery_signed_context ctx ON ctx.approval_id=child.receipt_id
  JOIN fatwa_delivery_intent intent ON intent.approval_id=child.receipt_id
  WHERE b.decision_id=NEW.delivery_id AND d.action='APPROVE'
   AND c.stage='ANSWERED' AND c.approved_answer_id=a.id
   AND d.evidence_version=c.evidence_version AND a.evidence_version=c.evidence_version
   AND a.revision=c.answer_revision AND p.ordinal=NEW.logical_ordinal
   AND (b.selection_mode='ALL' OR (b.selection_mode='TEXT_ONLY' AND p.ordinal=1 AND p.kind='TEXT'))
   AND parent.state='FAILED_REQUIRES_REVIEW' AND failure.reported='FAILED'
   AND proof.receipt_id=NEW.failure_evidence_id
   AND parent.case_key=c.public_ref AND parent.answer_revision=a.revision
   AND child.case_key=c.public_ref AND child.answer_revision=a.revision AND child.expected_parts=1
   AND child.receipt_id<>b.approval_id AND child.receipt_id<>parent.approval_id
   AND intent.ordinal=1 AND intent.state='STAGED' AND intent.provider='composite-simulator'
   AND NEW.scope->>'decision_id'=d.id::text
   AND NEW.scope->>'manifest_sha256'=m.sha256 AND b.manifest_sha256=m.sha256
   AND NEW.scope->>'capability_sha256'=b.capability_sha256
   AND NEW.scope->>'root_plan'=original.plan_fingerprint
   AND NEW.scope->>'parent_plan'=parent.plan_fingerprint
   AND NEW.scope->>'failure_sha256'=proof.envelope_sha256
   AND NEW.scope->'reviewer'->>'subject_id'=d.subject_id
   AND NEW.scope->'reviewer'->>'provider_id'=d.provider_id
   AND NEW.scope->'reviewer'->>'auth_epoch'=d.auth_epoch
   AND NEW.scope->'part'->>'sha256'=p.sha256
   AND (NEW.scope->'part'->>'ordinal')::integer=p.ordinal
   AND ctx.envelope->'evidence'->>'answer_sha256'=m.sha256
   AND (ctx.envelope->'evidence')-'source_digest'=(original_ctx.envelope->'evidence')-'source_digest'
   AND ctx.envelope->'evidence'->>'source_digest'=encode(sha256(convert_to(
       '["composite-retry.evidence.v1","'||(original_ctx.envelope->'evidence'->>'source_digest')||'",'||NEW.canonical_payload||']','UTF8')),'hex')
   AND ctx.envelope->'receipt'->>'approver_id'=d.subject_id
   AND ctx.envelope->'plan'->>'source_provider'='composite-simulator'
   AND (ctx.envelope->'receipt'->>'issued_at')::timestamptz>=failure.recorded_at
   AND ctx.envelope->'plan'->'steps'->0->>'idempotency_key'=intent.payload_sha256
   AND intent.payload_sha256=encode(sha256(convert_to(
       '["composite-retry.part.v1","'||(original_ctx.envelope->'plan'->'steps'->(NEW.logical_ordinal-1)->>'idempotency_key')||'",'||NEW.canonical_payload||']','UTF8')),'hex')
 ) THEN
  RAISE EXCEPTION 'signed failed predecessor and current canonical retry required' USING ERRCODE='23514';
 END IF;
 SELECT r.* INTO previous FROM composite_delivery_compositeretry r
 JOIN fatwa_delivery_intent parent ON parent.approval_id=r.approval_id
 WHERE parent.intent_key=NEW.parent_intent_id;
 IF NEW.retry_number=1 THEN
  IF previous.id IS NOT NULL OR NOT EXISTS (
   SELECT 1 FROM composite_delivery_compositedelivery b
   JOIN fatwa_delivery_intent p ON p.approval_id=b.approval_id
   WHERE b.decision_id=NEW.delivery_id AND p.intent_key=NEW.parent_intent_id
    AND p.ordinal=NEW.logical_ordinal
  ) THEN RAISE EXCEPTION 'retry must begin at exact original part' USING ERRCODE='23514'; END IF;
 ELSE
  IF previous.id IS NULL OR previous.delivery_id<>NEW.delivery_id
   OR previous.part_id<>NEW.part_id OR previous.logical_ordinal<>NEW.logical_ordinal
   OR previous.retry_number+1<>NEW.retry_number THEN
   RAISE EXCEPTION 'contiguous retry ancestry required' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER composite_retry_scope BEFORE INSERT ON composite_delivery_compositeretry
 FOR EACH ROW EXECUTE FUNCTION composite_retry_guard();
CREATE TRIGGER composite_retry_immutable BEFORE UPDATE OR DELETE ON composite_delivery_compositeretry
 FOR EACH ROW EXECUTE FUNCTION cw_immutable_history();
"""

REVERSE = """
DROP TRIGGER composite_retry_immutable ON composite_delivery_compositeretry;
DROP TRIGGER composite_retry_scope ON composite_delivery_compositeretry;
DROP FUNCTION composite_retry_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("composite_delivery", "0004_bounded_retry")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
