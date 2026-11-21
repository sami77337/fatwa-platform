"""Append-only identities/revisions/audit and exact typed source pin checks."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION pcol_series_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'collection identity immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF (SELECT count(*) FROM public_collections_collectionseries WHERE case_id=NEW.case_id)>=32
 OR NEW.public_id=NEW.id OR NEW.public_id=NEW.case_id THEN
  RAISE EXCEPTION 'collection identity bound' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pcol_series_guard BEFORE INSERT OR UPDATE OR DELETE ON public_collections_collectionseries
 FOR EACH ROW EXECUTE FUNCTION pcol_series_guard();

CREATE FUNCTION pcol_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s public_collections_collectionseries%ROWTYPE; c casework_case%ROWTYPE;
 parent_row public_collections_collectionrevision%ROWTYPE; member jsonb; ok boolean;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'collection revision immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 SELECT * INTO s FROM public_collections_collectionseries WHERE id=NEW.series_id;
 SELECT * INTO c FROM casework_case WHERE id=s.case_id FOR UPDATE;
 IF c.id IS NULL OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version
 OR NEW.number<>(SELECT COALESCE(max(number),0)+1 FROM public_collections_collectionrevision WHERE series_id=s.id)
 OR NEW.provider_id='' OR NEW.subject_id='' OR NEW.auth_epoch=''
 OR jsonb_typeof(NEW.payload)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>4
 OR NOT NEW.payload ?& ARRAY['title','introduction','members','featured']
 OR jsonb_typeof(NEW.payload->'title')<>'string' OR NEW.payload->>'title'!~'\S'
 OR char_length(NEW.payload->>'title')>160 OR jsonb_typeof(NEW.payload->'introduction')<>'string'
 OR char_length(NEW.payload->>'introduction')>4000 OR jsonb_typeof(NEW.payload->'featured')<>'boolean'
 OR jsonb_typeof(NEW.payload->'members')<>'array' OR jsonb_array_length(NEW.payload->'members')>16
 OR (s.kind<>'TOPIC' AND jsonb_array_length(NEW.payload->'members')=0) THEN
  RAISE EXCEPTION 'collection revision invalid' USING ERRCODE='23514'; END IF;
 IF NEW.parent_id IS NOT NULL THEN
  SELECT * INTO parent_row FROM public_collections_collectionrevision WHERE id=NEW.parent_id;
  IF s.kind<>'TOPIC' OR parent_row.series_id=s.id
   OR NOT EXISTS(SELECT 1 FROM public_collections_collectionseries WHERE id=parent_row.series_id AND kind='TOPIC')
   OR EXISTS(SELECT 1 FROM public_collections_collectionrevision WHERE series_id=parent_row.series_id AND number>parent_row.number)
   OR NOT EXISTS(SELECT 1 FROM public_collections_collectionaction WHERE revision_id=parent_row.id AND action='APPROVE') THEN
   RAISE EXCEPTION 'collection parent invalid' USING ERRCODE='23514'; END IF;
  IF EXISTS(WITH RECURSIVE parents AS (
      SELECT id,parent_id,series_id,1 AS depth FROM public_collections_collectionrevision WHERE id=NEW.parent_id
      UNION ALL SELECT r.id,r.parent_id,r.series_id,p.depth+1 FROM public_collections_collectionrevision r JOIN parents p ON r.id=p.parent_id WHERE p.depth<6
     ) SELECT 1 FROM parents WHERE series_id=s.id OR depth>=5) THEN
   RAISE EXCEPTION 'collection parent cycle or depth' USING ERRCODE='23514'; END IF;
 END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(NEW.payload->'members'))<>
    (SELECT count(DISTINCT (v->>'kind',v->>'id')) FROM jsonb_array_elements(NEW.payload->'members') v) THEN
  RAISE EXCEPTION 'collection duplicate member' USING ERRCODE='23514'; END IF;
 FOR member IN SELECT * FROM jsonb_array_elements(NEW.payload->'members') LOOP
  IF jsonb_typeof(member)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(member))<>5
   OR NOT member ?& ARRAY['kind','id','sha256','number','case_id']
   OR member->>'sha256'!~'^[a-f0-9]{64}$' OR member->>'number'!~'^[1-9][0-9]{0,6}$'
   OR NOT EXISTS(SELECT 1 FROM casework_case WHERE id::text=member->>'case_id') THEN
   RAISE EXCEPTION 'collection member pin invalid' USING ERRCODE='23514'; END IF;
  ok := false;
  IF member->>'kind'='PUBLICATION' THEN
   SELECT EXISTS(SELECT 1 FROM experimental_publication_publicationedition WHERE id::text=member->>'id'
     AND case_id::text=member->>'case_id' AND content_sha256=member->>'sha256' AND number=(member->>'number')::integer) INTO ok;
  ELSIF member->>'kind' IN ('PRESENTATION','SCHOLAR','LESSON') THEN
   SELECT EXISTS(SELECT 1 FROM public_knowledge_publicrevision r JOIN public_knowledge_publicseries p ON p.id=r.series_id
     WHERE r.id::text=member->>'id' AND p.case_id::text=member->>'case_id' AND p.kind=member->>'kind'
      AND r.sha256=member->>'sha256' AND r.number=(member->>'number')::integer) INTO ok;
  ELSIF member->>'kind'='LIBRARY' AND to_regclass('research_library_libraryversion') IS NOT NULL THEN
   EXECUTE 'SELECT EXISTS(SELECT 1 FROM research_library_libraryversion v JOIN research_library_libraryitem i ON i.id=v.item_id
     WHERE v.id::text=$1 AND i.case_id::text=$2 AND v.digest=$3 AND v.number=$4)'
     INTO ok USING member->>'id',member->>'case_id',member->>'sha256',(member->>'number')::integer;
  END IF;
  IF NOT ok THEN RAISE EXCEPTION 'collection exact source missing' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER pcol_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON public_collections_collectionrevision
 FOR EACH ROW EXECUTE FUNCTION pcol_revision_guard();

CREATE FUNCTION pcol_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public_collections_collectionrevision%ROWTYPE; reviewer public_collections_collectionaction%ROWTYPE; prior integer;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'collection action immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 SELECT * INTO r FROM public_collections_collectionrevision WHERE id=NEW.revision_id;
 PERFORM 1 FROM casework_case c JOIN public_collections_collectionseries s ON s.case_id=c.id WHERE s.id=r.series_id FOR UPDATE OF c;
 SELECT COALESCE(max(sequence),0) INTO prior FROM public_collections_collectionaction WHERE revision_id=r.id;
 SELECT * INTO reviewer FROM public_collections_collectionaction WHERE revision_id=r.id AND action='REVIEW';
 IF NEW.sequence<>prior+1 OR NEW.content_sha256<>r.sha256 OR NEW.provider_id='' OR NEW.subject_id='' OR NEW.auth_epoch=''
 OR (NEW.action<>'RELEASE' AND (NEW.expires_at IS NOT NULL OR NEW.requested_minutes<>0 OR NEW.note!~'\S'))
 OR (NEW.action='RELEASE' AND NEW.requested_minutes NOT IN (5,15,30,60))
 OR (NEW.action<>'REVOKE' AND NEW.related_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM public_collections_collectionrevision WHERE series_id=r.series_id AND number>r.number)
 OR EXISTS(SELECT 1 FROM public_collections_collectionaction WHERE revision_id=r.id AND action='WITHDRAW') THEN
  RAISE EXCEPTION 'collection action invalid' USING ERRCODE='23514'; END IF;
 IF NEW.action='REVIEW' AND (prior<>0 OR (NEW.provider_id,NEW.subject_id)=(r.provider_id,r.subject_id)) THEN
  RAISE EXCEPTION 'independent collection review required' USING ERRCODE='23514'; END IF;
 IF NEW.action='APPROVE' AND (prior<>1 OR reviewer.id IS NULL
  OR (NEW.provider_id,NEW.subject_id) IN ((r.provider_id,r.subject_id),(reviewer.provider_id,reviewer.subject_id))) THEN
  RAISE EXCEPTION 'independent collection approval required' USING ERRCODE='23514'; END IF;
 IF NEW.action IN ('RELEASE','REVOKE') AND NOT EXISTS(SELECT 1 FROM public_collections_collectionaction WHERE revision_id=r.id AND action='APPROVE') THEN
  RAISE EXCEPTION 'collection approval required' USING ERRCODE='23514'; END IF;
 IF NEW.action='RELEASE' AND (NEW.expires_at IS NULL OR NEW.expires_at<=CURRENT_TIMESTAMP OR NEW.expires_at>CURRENT_TIMESTAMP+interval '1 hour') THEN
  RAISE EXCEPTION 'bounded collection release required' USING ERRCODE='23514'; END IF;
 IF NEW.action='REVOKE' AND NOT EXISTS(SELECT 1 FROM public_collections_collectionaction WHERE id=NEW.related_id AND revision_id=r.id AND action='RELEASE') THEN
  RAISE EXCEPTION 'exact collection release required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pcol_action_guard BEFORE INSERT OR UPDATE OR DELETE ON public_collections_collectionaction
 FOR EACH ROW EXECUTE FUNCTION pcol_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("public_collections", "0001_initial"), ("public_knowledge", "0002_integrity")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER pcol_action_guard ON public_collections_collectionaction;
        DROP FUNCTION pcol_action_guard();
        DROP TRIGGER pcol_revision_guard ON public_collections_collectionrevision;
        DROP FUNCTION pcol_revision_guard();
        DROP TRIGGER pcol_series_guard ON public_collections_collectionseries;
        DROP FUNCTION pcol_series_guard();
    """,
        )
    ]
