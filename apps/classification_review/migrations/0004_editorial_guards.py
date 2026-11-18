"""Own provenance guard; additive guard on canonical actions for bound editions only."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION classification_editorial_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r classification_review_classificationrevision%ROWTYPE;
DECLARE k knowledge_links_knowledgerevision%ROWTYPE;
DECLARE s experimental_publication_publicationedition%ROWTYPE;
DECLARE e experimental_publication_publicationedition%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'classification editorial binding immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO r FROM classification_review_classificationrevision WHERE id=NEW.revision_id;
 SELECT * INTO k FROM knowledge_links_knowledgerevision WHERE id=r.knowledge_id;
 SELECT * INTO s FROM experimental_publication_publicationedition WHERE id=k.publication_id;
 SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=NEW.edition_id;
 PERFORM 1 FROM casework_case WHERE id=s.case_id FOR UPDATE;
 IF r.id IS NULL OR e.id IS NULL OR e.case_id<>s.case_id OR e.id=s.id
  OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.policy_id !~ '\S'
  OR NEW.subject_id<>e.subject_id OR NEW.provider_id<>e.provider_id OR NEW.auth_epoch<>e.auth_epoch
  OR NEW.snapshot_sha256 !~ '^[a-f0-9]{64}$'
  OR NEW.snapshot->>'classification_id' IS DISTINCT FROM r.id::text
  OR NEW.snapshot->>'classification_number' IS DISTINCT FROM r.number::text
  OR NEW.snapshot->>'classification_digest' IS DISTINCT FROM r.snapshot_sha256
  OR NEW.snapshot->>'label' IS DISTINCT FROM r.label
  OR NEW.snapshot->>'source_edition_id' IS DISTINCT FROM s.id::text
  OR NEW.snapshot->>'source_edition_number' IS DISTINCT FROM s.number::text
  OR NEW.snapshot->>'source_edition_digest' IS DISTINCT FROM s.content_sha256
  OR NEW.snapshot->>'target_edition_id' IS DISTINCT FROM e.id::text
  OR NEW.snapshot->>'target_edition_number' IS DISTINCT FROM e.number::text
  OR NEW.snapshot->>'target_edition_digest' IS DISTINCT FROM e.content_sha256
  OR NEW.snapshot->>'policy_id' IS DISTINCT FROM NEW.policy_id
  OR NEW.snapshot->>'mode' IS DISTINCT FROM 'CLOSED_SYNTHETIC_SIMULATION'
  OR e.category<>r.label OR e.title<>s.title OR e.body<>s.body OR e.citations<>s.citations
  OR e.answer_id<>s.answer_id OR e.decision_id<>s.decision_id OR e.evidence_version<>s.evidence_version
  OR e.number<>(SELECT max(number) FROM experimental_publication_publicationedition WHERE case_id=s.case_id)
  OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id)
  OR EXISTS (SELECT 1 FROM classification_review_classificationrevision WHERE series=r.series AND number>r.number)
  OR NOT EXISTS (SELECT 1 FROM classification_review_classificationaction WHERE revision_id=r.id AND action='APPROVE')
  OR EXISTS (SELECT 1 FROM classification_review_classificationaction WHERE revision_id=r.id AND action IN ('REJECT','WITHDRAW'))
  OR EXISTS (SELECT 1 FROM knowledge_links_knowledgerevision WHERE series=k.series AND number>k.number)
  OR NOT EXISTS (SELECT 1 FROM knowledge_links_knowledgeaction WHERE revision_id=k.id AND action='APPROVE')
  OR EXISTS (SELECT 1 FROM knowledge_links_knowledgeaction WHERE revision_id=k.id AND action='WITHDRAW')
  OR NOT EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=s.id AND action='APPROVE')
  OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=s.id AND action='WITHDRAW')
  OR s.number<>(SELECT max(p.number) FROM experimental_publication_publicationedition p
    JOIN experimental_publication_publicationaction a ON a.edition_id=p.id AND a.action='APPROVE'
    WHERE p.case_id=s.case_id)
 THEN RAISE EXCEPTION 'classification editorial binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER classification_editorial_binding_guard BEFORE INSERT OR UPDATE OR DELETE
 ON classification_review_editorialbinding FOR EACH ROW EXECUTE FUNCTION classification_editorial_binding_guard();

CREATE FUNCTION classification_editorial_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b classification_review_editorialbinding%ROWTYPE;
DECLARE r classification_review_classificationrevision%ROWTYPE;
DECLARE k knowledge_links_knowledgerevision%ROWTYPE;
DECLARE s experimental_publication_publicationedition%ROWTYPE;
BEGIN
 SELECT * INTO b FROM classification_review_editorialbinding WHERE edition_id=NEW.edition_id;
 IF b.id IS NULL OR NEW.action='WITHDRAW' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM classification_review_classificationrevision WHERE id=b.revision_id;
 SELECT * INTO k FROM knowledge_links_knowledgerevision WHERE id=r.knowledge_id;
 SELECT * INTO s FROM experimental_publication_publicationedition WHERE id=k.publication_id;
 PERFORM 1 FROM casework_case WHERE id=s.case_id FOR UPDATE;
 IF current_setting('fatwa.classification_editorial', true) IS DISTINCT FROM b.id::text||':'||NEW.action
  OR EXISTS (SELECT 1 FROM classification_review_classificationrevision WHERE series=r.series AND number>r.number)
  OR NOT EXISTS (SELECT 1 FROM classification_review_classificationaction WHERE revision_id=r.id AND action='APPROVE')
  OR EXISTS (SELECT 1 FROM classification_review_classificationaction WHERE revision_id=r.id AND action IN ('REJECT','WITHDRAW'))
  OR EXISTS (SELECT 1 FROM knowledge_links_knowledgerevision WHERE series=k.series AND number>k.number)
  OR EXISTS (SELECT 1 FROM knowledge_links_knowledgeaction WHERE revision_id=k.id AND action='WITHDRAW')
  OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=s.id AND action='WITHDRAW')
  OR s.number<>(SELECT max(p.number) FROM experimental_publication_publicationedition p
    JOIN experimental_publication_publicationaction a ON a.edition_id=p.id AND a.action='APPROVE'
    WHERE p.case_id=s.case_id)
  OR (NEW.action='APPROVE' AND (
    (NEW.provider_id=r.provider_id AND NEW.subject_id=r.subject_id)
    OR EXISTS (SELECT 1 FROM classification_review_classificationaction
               WHERE revision_id=r.id AND action='APPROVE'
               AND provider_id=NEW.provider_id AND subject_id=NEW.subject_id)))
 THEN RAISE EXCEPTION 'classification editorial guarded review required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER classification_editorial_action_guard BEFORE INSERT
 ON experimental_publication_publicationaction FOR EACH ROW EXECUTE FUNCTION classification_editorial_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("classification_review", "0003_editorialbinding")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER classification_editorial_action_guard ON experimental_publication_publicationaction;
        DROP FUNCTION classification_editorial_action_guard();
        DROP TRIGGER classification_editorial_binding_guard ON classification_review_editorialbinding;
        DROP FUNCTION classification_editorial_binding_guard();
    """,
        )
    ]
