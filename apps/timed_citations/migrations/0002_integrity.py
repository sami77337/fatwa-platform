"""Append-only lineage and exact canonical owner/case/version database bindings."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION timed_citations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE;
DECLARE a casework_answerrevision%ROWTYPE;
DECLARE p timed_citations_timedcitation%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'timed citation history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 SELECT * INTO a FROM casework_answerrevision WHERE id=NEW.answer_id;
 SELECT * INTO p FROM timed_citations_timedcitation WHERE series=NEW.series ORDER BY number DESC LIMIT 1;
 IF a.case_id IS DISTINCT FROM c.id OR a.revision<>c.answer_revision
 OR a.evidence_version<>c.evidence_version OR c.stage<>'UNDER_REVIEW'
 OR c.approved_answer_id IS NOT NULL
 OR EXISTS (SELECT 1 FROM casework_casedecision WHERE answer_id=a.id)
 OR NEW.number<>COALESCE(p.number,0)+1
 OR (p.id IS NULL AND NEW.previous_id IS NOT NULL)
 OR (p.id IS NOT NULL AND (NEW.previous_id IS DISTINCT FROM p.id OR NEW.case_id<>p.case_id))
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.reason !~ '\S'
 OR jsonb_typeof(NEW.snapshot)<>'object'
 OR NEW.snapshot->>'duration_ms' IS DISTINCT FROM NEW.duration_ms::text
 THEN RAISE EXCEPTION 'timed citation lineage invalid' USING ERRCODE='23514'; END IF;
 IF NEW.attachment_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM case_attachments_caseattachment t JOIN casework_caseevidence e ON e.id=t.evidence_id
  WHERE t.id=NEW.attachment_id AND t.case_id=c.id AND e.case_id=c.id AND t.kind='audio'
   AND NEW.snapshot->>'kind'='ATTACHMENT' AND NEW.snapshot->>'id'=t.id::text
   AND NEW.snapshot->>'sha256'=t.sha256 AND NEW.snapshot->>'version'=e.version::text
   AND NEW.snapshot->>'duration_ms'=floor((t.validation_metadata->>'duration_seconds')::numeric *1000)::text
 ) THEN RAISE EXCEPTION 'timed attachment binding invalid' USING ERRCODE='23514'; END IF;
 IF NEW.part_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM answer_media_answerpart t JOIN casework_answerrevision r ON r.id=t.manifest_id
  WHERE t.id=NEW.part_id AND r.case_id=c.id AND t.kind='AUDIO'
   AND NEW.snapshot->>'kind'='ANSWER_MEDIA' AND NEW.snapshot->>'id'=t.id::text
   AND NEW.snapshot->>'sha256'=t.sha256 AND NEW.snapshot->>'version'=r.revision::text
   AND NEW.snapshot->>'duration_ms'=floor((t.metadata->>'duration_seconds')::numeric *1000)::text
 ) THEN RAISE EXCEPTION 'timed answer part binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER timed_citations_guard BEFORE INSERT OR UPDATE OR DELETE ON timed_citations_timedcitation
 FOR EACH ROW EXECUTE FUNCTION timed_citations_guard();
CREATE FUNCTION timed_citations_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r timed_citations_timedcitation%ROWTYPE;
DECLARE c casework_case%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'timed actions immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO r FROM timed_citations_timedcitation WHERE id=NEW.citation_id;
 SELECT * INTO c FROM casework_case WHERE id=r.case_id FOR UPDATE;
 IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR r.number<>(SELECT max(number) FROM timed_citations_timedcitation WHERE series=r.series)
 OR EXISTS (SELECT 1 FROM timed_citations_timedcitationaction WHERE citation_id=r.id AND action='WITHDRAW')
 OR (NEW.action='CONFIRM' AND (
     c.stage<>'UNDER_REVIEW' OR c.approved_answer_id IS NOT NULL
     OR NOT EXISTS (SELECT 1 FROM casework_answerrevision WHERE id=r.answer_id
                    AND revision=c.answer_revision AND evidence_version=c.evidence_version)
     OR EXISTS (SELECT 1 FROM casework_casedecision WHERE answer_id=r.answer_id)
 )) THEN RAISE EXCEPTION 'timed action not current' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER timed_citations_action_guard BEFORE INSERT OR UPDATE OR DELETE ON timed_citations_timedcitationaction
 FOR EACH ROW EXECUTE FUNCTION timed_citations_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("timed_citations", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER timed_citations_action_guard ON timed_citations_timedcitationaction;
        DROP FUNCTION timed_citations_action_guard();
        DROP TRIGGER timed_citations_guard ON timed_citations_timedcitation;
        DROP FUNCTION timed_citations_guard();
    """,
        )
    ]
