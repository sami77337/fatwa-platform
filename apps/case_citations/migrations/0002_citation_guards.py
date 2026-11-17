from django.db import migrations

SQL = """
CREATE FUNCTION case_citation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'answer citations immutable' USING ERRCODE='23514';
 END IF;
 IF length(NEW.editorial_note)>2000 OR NEW.source_sha256 !~ '^[a-f0-9]{64}$'
 OR NOT EXISTS (
  SELECT 1 FROM casework_answerrevision a
  JOIN casework_case c ON c.id=a.case_id
  JOIN casework_caseevent v ON v.case_id=c.id AND v.sequence=c.revision
  JOIN reference_referenceheading h ON h.id=NEW.heading_id
  JOIN reference_referenceedition e ON e.id=h.edition_id
  JOIN reference_referencework w ON w.id=e.work_id
  WHERE a.id=NEW.answer_id AND a.revision=c.answer_revision
   AND a.created_at >= transaction_timestamp()
   AND a.evidence_version=c.evidence_version AND c.approved_answer_id IS NULL
   AND c.stage='UNDER_REVIEW' AND v.action='SAVE_ANSWER' AND v.answer_id=a.id
   AND NOT EXISTS(SELECT 1 FROM casework_casedecision d WHERE d.answer_id=a.id)
   AND NEW.source->>'kind'='SOURCE_BOOK_TOC_NOT_FATWAS'
   AND NEW.source->>'edition_id'=e.id::text
   AND NEW.source->>'source_row_id'=h.source_row_id::text
   AND NEW.source->>'heading_title'=h.title_original
   AND NEW.source->>'work_title'=w.title_original
   AND NEW.source->>'source_namespace'=w.source_namespace
   AND NEW.source->>'source_book_id'=w.source_book_id AND w.source_book_id='622'
   AND NEW.source->>'edition_key'=e.edition_key
   AND NEW.source->>'edition_title'=e.title
   AND NEW.source->>'publisher'=e.publisher
   AND NEW.source->>'source_input_sha256'=e.source_input_sha256
   AND NEW.source->>'source_archive_sha256'=e.source_archive_sha256
   AND NEW.source->>'printed_part'=h.source_part
   AND NEW.source->>'printed_page'=h.source_page_number::text
 ) THEN
  RAISE EXCEPTION 'citation source or answer mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER case_citation_guard BEFORE INSERT OR UPDATE OR DELETE
 ON case_citations_answercitation FOR EACH ROW EXECUTE FUNCTION case_citation_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("case_citations", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER case_citation_guard ON case_citations_answercitation;
        DROP FUNCTION case_citation_guard();
    """,
        )
    ]
