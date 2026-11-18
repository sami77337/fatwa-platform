"""Append-only lineage and exact canonical owner/case/version database bindings."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION pdf_citations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE;
DECLARE a casework_answerrevision%ROWTYPE;
DECLARE p pdf_citations_pdfcitation%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'pdf citation history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 SELECT * INTO a FROM casework_answerrevision WHERE id=NEW.answer_id;
 SELECT * INTO p FROM pdf_citations_pdfcitation WHERE series=NEW.series ORDER BY number DESC LIMIT 1;
 IF a.case_id IS DISTINCT FROM c.id OR a.revision<>c.answer_revision
 OR a.evidence_version<>c.evidence_version OR c.stage<>'UNDER_REVIEW'
 OR c.approved_answer_id IS NOT NULL
 OR EXISTS (SELECT 1 FROM casework_casedecision WHERE answer_id=a.id)
 OR NEW.number<>COALESCE(p.number,0)+1
 OR (p.id IS NULL AND NEW.previous_id IS NOT NULL)
 OR (p.id IS NOT NULL AND (NEW.previous_id IS DISTINCT FROM p.id OR NEW.case_id<>p.case_id))
 OR NEW.printed_label<>btrim(NEW.printed_label) OR NEW.printed_label ~ '[[:cntrl:]]'
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.reason !~ '\S'
 OR jsonb_typeof(NEW.snapshot)<>'object'
 OR NEW.snapshot->>'page_count' IS DISTINCT FROM NEW.page_count::text
 THEN RAISE EXCEPTION 'pdf citation lineage invalid' USING ERRCODE='23514'; END IF;
 IF NEW.attachment_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM case_attachments_caseattachment t JOIN casework_caseevidence e ON e.id=t.evidence_id
  WHERE t.id=NEW.attachment_id AND t.case_id=c.id AND e.case_id=c.id AND t.kind='pdf' AND t.media_type='application/pdf'
   AND NEW.snapshot->>'kind'='ATTACHMENT' AND NEW.snapshot->>'id'=t.id::text
   AND NEW.snapshot->>'sha256'=t.sha256 AND NEW.snapshot->>'version'=e.version::text
   AND NEW.snapshot->>'page_count'=t.validation_metadata->>'pages'
 ) THEN RAISE EXCEPTION 'pdf attachment binding invalid' USING ERRCODE='23514'; END IF;
 IF NEW.part_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM answer_media_answerpart t JOIN casework_answerrevision r ON r.id=t.manifest_id
  WHERE t.id=NEW.part_id AND r.case_id=c.id AND t.kind='FILE' AND t.media_type='application/pdf'
   AND NEW.snapshot->>'kind'='ANSWER_MEDIA' AND NEW.snapshot->>'id'=t.id::text
   AND NEW.snapshot->>'sha256'=t.sha256 AND NEW.snapshot->>'version'=r.revision::text
   AND NEW.snapshot->>'page_count'=t.metadata->>'pages'
 ) THEN RAISE EXCEPTION 'pdf answer part binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pdf_citations_guard BEFORE INSERT OR UPDATE OR DELETE ON pdf_citations_pdfcitation
 FOR EACH ROW EXECUTE FUNCTION pdf_citations_guard();
CREATE FUNCTION pdf_citations_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r pdf_citations_pdfcitation%ROWTYPE;
DECLARE c casework_case%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'pdf actions immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO r FROM pdf_citations_pdfcitation WHERE id=NEW.citation_id;
 SELECT * INTO c FROM casework_case WHERE id=r.case_id FOR UPDATE;
 IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR r.number<>(SELECT max(number) FROM pdf_citations_pdfcitation WHERE series=r.series)
 OR EXISTS (SELECT 1 FROM pdf_citations_pdfcitationaction WHERE citation_id=r.id AND action='WITHDRAW')
 OR (NEW.action='CONFIRM' AND (
     c.stage<>'UNDER_REVIEW' OR c.approved_answer_id IS NOT NULL
     OR NOT EXISTS (SELECT 1 FROM casework_answerrevision WHERE id=r.answer_id
                    AND revision=c.answer_revision AND evidence_version=c.evidence_version)
     OR EXISTS (SELECT 1 FROM casework_casedecision WHERE answer_id=r.answer_id)
 )) THEN RAISE EXCEPTION 'pdf action not current' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pdf_citations_action_guard BEFORE INSERT OR UPDATE OR DELETE ON pdf_citations_pdfcitationaction
 FOR EACH ROW EXECUTE FUNCTION pdf_citations_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("pdf_citations", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER pdf_citations_action_guard ON pdf_citations_pdfcitationaction;
        DROP FUNCTION pdf_citations_action_guard();
        DROP TRIGGER pdf_citations_guard ON pdf_citations_pdfcitation;
        DROP FUNCTION pdf_citations_guard();
    """,
        )
    ]
