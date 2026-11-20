"""Immutable owner/source bindings and append-only research audit history."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION research_collection_owner_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'research collection history retained' USING ERRCODE='23514';
 END IF;
 IF NEW.provider_id='' OR NEW.subject_id='' OR NEW.title !~ '\S'
 OR (TG_OP='UPDATE' AND (NEW.case_id,NEW.provider_id,NEW.subject_id,NEW.created_at)
      IS DISTINCT FROM (OLD.case_id,OLD.provider_id,OLD.subject_id,OLD.created_at)) THEN
  RAISE EXCEPTION 'research collection owner immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_collection_owner_guard BEFORE INSERT OR UPDATE OR DELETE
 ON research_workspace_researchcollection FOR EACH ROW
 EXECUTE FUNCTION research_collection_owner_guard();

CREATE FUNCTION research_collection_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.collection_id,NEW.resource,NEW.resource_sha256,NEW.created_at)
     IS DISTINCT FROM (OLD.collection_id,OLD.resource,OLD.resource_sha256,OLD.created_at) THEN
  RAISE EXCEPTION 'research source binding immutable' USING ERRCODE='23514';
 END IF;
 IF jsonb_typeof(NEW.resource)<>'object' OR NEW.resource->>'kind' NOT IN ('REFERENCE','TRANSCRIPT','KNOWLEDGE')
 OR NEW.resource_sha256 !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'research source binding invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_collection_item_guard BEFORE INSERT OR UPDATE
 ON research_workspace_researchitem FOR EACH ROW
 EXECUTE FUNCTION research_collection_item_guard();

CREATE FUNCTION research_collection_search_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  RAISE EXCEPTION 'saved search immutable; save new instructions' USING ERRCODE='23514';
 END IF;
 IF NEW.title !~ '\S' OR jsonb_typeof(NEW.filters)<>'object' THEN
  RAISE EXCEPTION 'saved search invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_collection_search_guard BEFORE INSERT OR UPDATE
 ON research_workspace_savedresearchsearch FOR EACH ROW
 EXECUTE FUNCTION research_collection_search_guard();

CREATE FUNCTION research_collection_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c research_workspace_researchcollection%ROWTYPE;
DECLARE prior research_workspace_researchcollectionevent%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'research collection audit immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM research_workspace_researchcollection WHERE id=NEW.collection_id FOR UPDATE;
 SELECT * INTO prior FROM research_workspace_researchcollectionevent
  WHERE collection_id=NEW.collection_id ORDER BY revision DESC LIMIT 1;
 IF NEW.subject_id<>c.subject_id OR NEW.provider_id<>c.provider_id OR NEW.auth_epoch=''
 OR NEW.revision<>c.revision OR NEW.revision<>COALESCE(prior.revision,0)+1
 OR NEW.previous_sha256<>COALESCE(prior.sha256,repeat('0',64))
 OR NEW.state_sha256 !~ '^[a-f0-9]{64}$' OR NEW.sha256 !~ '^[a-f0-9]{64}$'
 OR NEW.action NOT IN ('CREATE','RENAME','ARCHIVE','RESTORE','ADD','NOTE','REMOVE','MOVE','SAVE_SEARCH','REMOVE_SEARCH')
 OR jsonb_typeof(NEW.details)<>'object'
 OR NOT EXISTS(SELECT 1 FROM casework_case k WHERE k.id=c.case_id
                AND k.revision=NEW.case_revision AND k.evidence_version=NEW.evidence_version) THEN
  RAISE EXCEPTION 'research collection audit invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_collection_event_guard BEFORE INSERT OR UPDATE OR DELETE
 ON research_workspace_researchcollectionevent FOR EACH ROW
 EXECUTE FUNCTION research_collection_event_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("research_workspace", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
DROP TRIGGER research_collection_event_guard ON research_workspace_researchcollectionevent;
DROP FUNCTION research_collection_event_guard();
DROP TRIGGER research_collection_search_guard ON research_workspace_savedresearchsearch;
DROP FUNCTION research_collection_search_guard();
DROP TRIGGER research_collection_item_guard ON research_workspace_researchitem;
DROP FUNCTION research_collection_item_guard();
DROP TRIGGER research_collection_owner_guard ON research_workspace_researchcollection;
DROP FUNCTION research_collection_owner_guard();
""",
        )
    ]
