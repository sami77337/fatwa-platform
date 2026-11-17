"""Keep revocation possible after rights lapse or the publication is superseded."""

from importlib import import_module

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION knowledge_links_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
 OR (NEW.action='APPROVE' AND (
     NOT EXISTS (SELECT 1 FROM casework_case WHERE id=e.case_id AND stage='ANSWERED'
                 AND approved_answer_id=e.answer_id AND evidence_version=e.evidence_version)
     OR EXISTS (SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='WITHDRAW')
     OR e.number<>(SELECT max(p.number) FROM experimental_publication_publicationedition p
                   JOIN experimental_publication_publicationaction a ON a.edition_id=p.id AND a.action='APPROVE'
                   WHERE p.case_id=e.case_id)
     OR (NEW.provider_id=r.provider_id AND NEW.subject_id=r.subject_id)
 )) THEN RAISE EXCEPTION 'knowledge independent current review required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

# Restore exactly the previous guard on rollback, without rewriting historical SQL.
previous = import_module("apps.knowledge_links.migrations.0002_integrity").SQL
REVERSE = previous[previous.index("CREATE FUNCTION knowledge_links_action_guard()") :]
REVERSE = REVERSE[: REVERSE.index("CREATE TRIGGER knowledge_links_action_guard")].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)


class Migration(migrations.Migration):
    dependencies = [("knowledge_links", "0002_integrity")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
