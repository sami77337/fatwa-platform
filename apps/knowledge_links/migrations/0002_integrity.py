"""Enforce immutable history and same-publication/same-case source bindings."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION knowledge_links_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e experimental_publication_publicationedition%ROWTYPE;
DECLARE prior knowledge_links_knowledgerevision%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'knowledge history immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=NEW.publication_id;
 PERFORM 1 FROM casework_case WHERE id=e.case_id FOR UPDATE;
 SELECT * INTO prior FROM knowledge_links_knowledgerevision WHERE series=NEW.series ORDER BY number DESC LIMIT 1;
 IF NEW.number <> COALESCE(prior.number,0)+1
 OR (prior.id IS NOT NULL AND prior.publication_id<>NEW.publication_id)
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR NEW.reason !~ '\S' OR NEW.snapshot_sha256 !~ '^[a-f0-9]{64}$'
 OR jsonb_typeof(NEW.snapshot)<>'object'
 OR NOT EXISTS (SELECT 1 FROM casework_case WHERE id=e.case_id AND stage='ANSWERED'
                AND approved_answer_id=e.answer_id AND evidence_version=e.evidence_version)
 OR NOT EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='APPROVE')
 OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='WITHDRAW')
 OR e.number<>(SELECT max(p.number) FROM experimental_publication_publicationedition p
               JOIN experimental_publication_publicationaction a ON a.edition_id=p.id AND a.action='APPROVE'
               WHERE p.case_id=e.case_id) THEN
  RAISE EXCEPTION 'knowledge source or lineage invalid' USING ERRCODE='23514';
 END IF;
 IF NEW.heading_id IS NOT NULL AND (
  NEW.snapshot->>'kind' IS DISTINCT FROM 'REFERENCE'
  OR NOT EXISTS (SELECT 1 FROM reference_referenceheading h WHERE h.id=NEW.heading_id
      AND h.edition_id::text=NEW.snapshot->'source'->>'edition_id'
      AND h.source_row_id::text=NEW.snapshot->'source'->>'source_row_id')
  OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(e.citations) c
                WHERE c->'source'=NEW.snapshot->'source'
                AND c->>'source_sha256'=NEW.snapshot->>'source_sha256')
 ) THEN RAISE EXCEPTION 'knowledge cited source required' USING ERRCODE='23514'; END IF;
 IF NEW.transcript_id IS NOT NULL AND (
  NEW.snapshot->>'kind' IS DISTINCT FROM 'TRANSCRIPT'
  OR NEW.snapshot->>'link_id' IS DISTINCT FROM NEW.transcript_id::text
  OR NOT EXISTS (SELECT 1 FROM transcript_case_links_transcriptlink t
                 JOIN transcript_case_links_transcriptupload u ON u.id=t.upload_id
                 JOIN casework_caseevidence v ON v.id=t.evidence_id
                 WHERE t.id=NEW.transcript_id AND t.case_id=e.case_id AND u.case_id=e.case_id
                  AND v.case_id=e.case_id AND v.version<=e.evidence_version
                  AND u.sha256=NEW.snapshot->>'bundle_sha256')
 ) THEN RAISE EXCEPTION 'knowledge transcript binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER knowledge_links_revision_guard BEFORE INSERT OR UPDATE OR DELETE
 ON knowledge_links_knowledgerevision FOR EACH ROW EXECUTE FUNCTION knowledge_links_revision_guard();

CREATE FUNCTION knowledge_links_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r knowledge_links_knowledgerevision%ROWTYPE;
DECLARE e experimental_publication_publicationedition%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'knowledge actions immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO r FROM knowledge_links_knowledgerevision WHERE id=NEW.revision_id;
 SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=r.publication_id;
 PERFORM 1 FROM casework_case WHERE id=e.case_id FOR UPDATE;
 IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR r.number<>(SELECT max(number) FROM knowledge_links_knowledgerevision WHERE series=r.series)
 OR EXISTS (SELECT 1 FROM knowledge_links_knowledgeaction WHERE revision_id=r.id AND action='WITHDRAW')
 OR NOT EXISTS (SELECT 1 FROM casework_case WHERE id=e.case_id AND stage='ANSWERED'
                AND approved_answer_id=e.answer_id AND evidence_version=e.evidence_version)
 OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='WITHDRAW')
 OR e.number<>(SELECT max(p.number) FROM experimental_publication_publicationedition p
               JOIN experimental_publication_publicationaction a ON a.edition_id=p.id AND a.action='APPROVE'
               WHERE p.case_id=e.case_id)
 OR (NEW.action='APPROVE' AND NEW.provider_id=r.provider_id AND NEW.subject_id=r.subject_id)
 THEN RAISE EXCEPTION 'knowledge independent current review required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER knowledge_links_action_guard BEFORE INSERT OR UPDATE OR DELETE
 ON knowledge_links_knowledgeaction FOR EACH ROW EXECUTE FUNCTION knowledge_links_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("knowledge_links", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER knowledge_links_action_guard ON knowledge_links_knowledgeaction;
        DROP FUNCTION knowledge_links_action_guard();
        DROP TRIGGER knowledge_links_revision_guard ON knowledge_links_knowledgerevision;
        DROP FUNCTION knowledge_links_revision_guard();
    """,
        )
    ]
