"""Append-only review history, serialized lineage and mutually exclusive decisions."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION classification_review_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE k knowledge_links_knowledgerevision%ROWTYPE;
DECLARE e experimental_publication_publicationedition%ROWTYPE;
DECLARE r classification_review_classificationrevision%ROWTYPE;
DECLARE prior classification_review_classificationrevision%ROWTYPE;
DECLARE is_revision boolean := TG_TABLE_NAME='classification_review_classificationrevision';
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'classification history immutable' USING ERRCODE='23514';
 END IF;
 IF is_revision THEN
  SELECT * INTO k FROM knowledge_links_knowledgerevision WHERE id=NEW.knowledge_id;
 ELSE
  SELECT * INTO r FROM classification_review_classificationrevision WHERE id=NEW.revision_id;
  SELECT * INTO k FROM knowledge_links_knowledgerevision WHERE id=r.knowledge_id;
 END IF;
 SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=k.publication_id;
 PERFORM 1 FROM casework_case WHERE id=e.case_id FOR UPDATE;
 IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR k.id IS NULL OR e.id IS NULL THEN
  RAISE EXCEPTION 'classification binding invalid' USING ERRCODE='23514';
 END IF;
 IF is_revision THEN
  SELECT * INTO prior FROM classification_review_classificationrevision
   WHERE series=NEW.series ORDER BY number DESC LIMIT 1;
  IF NEW.number<>COALESCE(prior.number,0)+1
   OR (prior.id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM knowledge_links_knowledgerevision
       WHERE id=prior.knowledge_id AND publication_id=e.id))
   OR NEW.label !~ '\S' OR NEW.reason !~ '\S' OR NEW.snapshot_sha256 !~ '^[a-f0-9]{64}$'
   OR NEW.snapshot->>'knowledge_id' IS DISTINCT FROM k.id::text
   OR NEW.snapshot->>'knowledge_number' IS DISTINCT FROM k.number::text
   OR NEW.snapshot->>'publication_id' IS DISTINCT FROM e.id::text
   OR NEW.snapshot->>'publication_number' IS DISTINCT FROM e.number::text
   OR NEW.snapshot->>'publication_digest' IS DISTINCT FROM e.content_sha256
   OR NEW.snapshot->>'existing_category' IS DISTINCT FROM e.category
   OR NEW.snapshot->>'namespace' IS DISTINCT FROM 'EXPERIMENTAL_GENERAL_LABEL'
   OR NEW.snapshot->>'source_digest' IS DISTINCT FROM k.snapshot_sha256
   OR NEW.snapshot->'source' IS DISTINCT FROM k.snapshot THEN
   RAISE EXCEPTION 'classification lineage or snapshot invalid' USING ERRCODE='23514';
  END IF;
 ELSE
  IF NEW.note !~ '\S'
   OR r.number<>(SELECT max(number) FROM classification_review_classificationrevision WHERE series=r.series)
   OR EXISTS (SELECT 1 FROM classification_review_classificationaction WHERE revision_id=r.id AND action='WITHDRAW')
   OR (NEW.action<>'WITHDRAW' AND (
       (NEW.provider_id=r.provider_id AND NEW.subject_id=r.subject_id)
       OR EXISTS (SELECT 1 FROM classification_review_classificationaction
                  WHERE revision_id=r.id AND action IN ('APPROVE','REJECT')))) THEN
   RAISE EXCEPTION 'classification independent decision conflict' USING ERRCODE='23514';
  END IF;
  IF NEW.action='WITHDRAW' THEN RETURN NEW; END IF;
 END IF;
 IF k.heading_id IS NULL
  OR k.number<>(SELECT max(number) FROM knowledge_links_knowledgerevision WHERE series=k.series)
  OR NOT EXISTS (SELECT 1 FROM knowledge_links_knowledgeaction WHERE revision_id=k.id AND action='APPROVE')
  OR EXISTS (SELECT 1 FROM knowledge_links_knowledgeaction WHERE revision_id=k.id AND action='WITHDRAW')
  OR NOT EXISTS (SELECT 1 FROM casework_case WHERE id=e.case_id AND stage='ANSWERED'
                AND approved_answer_id=e.answer_id AND evidence_version=e.evidence_version)
  OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='WITHDRAW')
  OR NOT EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='APPROVE')
  OR e.number<>(SELECT max(p.number) FROM experimental_publication_publicationedition p
               JOIN experimental_publication_publicationaction a ON a.edition_id=p.id AND a.action='APPROVE'
               WHERE p.case_id=e.case_id) THEN
  RAISE EXCEPTION 'classification current reviewed source required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER classification_review_revision_guard BEFORE INSERT OR UPDATE OR DELETE
 ON classification_review_classificationrevision FOR EACH ROW EXECUTE FUNCTION classification_review_guard();
CREATE TRIGGER classification_review_action_guard BEFORE INSERT OR UPDATE OR DELETE
 ON classification_review_classificationaction FOR EACH ROW EXECUTE FUNCTION classification_review_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("classification_review", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER classification_review_action_guard ON classification_review_classificationaction;
        DROP TRIGGER classification_review_revision_guard ON classification_review_classificationrevision;
        DROP FUNCTION classification_review_guard();
    """,
        )
    ]
