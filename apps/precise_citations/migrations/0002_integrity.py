from django.db import migrations

SQL = r"""
CREATE FUNCTION precise_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a casework_answerrevision%ROWTYPE; c casework_case%ROWTYPE;
 s precise_citations_citationset%ROWTYPE; previous_anchor precise_citations_citationanchor%ROWTYPE;
 previous_set precise_citations_citationset%ROWTYPE; target casework_answerrevision%ROWTYPE;
 ok boolean; source_kind text; source_id text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'precise citation immutable' USING ERRCODE='23514'; END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
 THEN RAISE EXCEPTION 'precise citation seal invalid' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 IF TG_TABLE_NAME='precise_citations_citationset' THEN
  SELECT * INTO a FROM casework_answerrevision WHERE id=NEW.answer_id;
 ELSE
  SELECT * INTO s FROM precise_citations_citationset WHERE id=NEW.citation_set_id;
  SELECT * INTO a FROM casework_answerrevision WHERE id=s.answer_id;
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=a.case_id FOR UPDATE;
 IF c.id IS NULL OR a.revision<>c.answer_revision OR a.evidence_version<>c.evidence_version
 THEN RAISE EXCEPTION 'precise current answer required' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='precise_citations_citationset' THEN
  IF NEW.subject_id<>a.subject_id OR NEW.provider_id<>a.provider_id OR NEW.auth_epoch<>a.auth_epoch
   OR NEW.request_digest !~ '^[a-f0-9]{64}$' THEN
   RAISE EXCEPTION 'precise answer author mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.previous_id IS NOT NULL THEN
   SELECT p.* INTO previous_set FROM precise_citations_citationset p JOIN casework_answerrevision r ON r.id=p.answer_id
    WHERE r.case_id=c.id AND r.revision=a.revision-1;
   IF NEW.previous_id IS DISTINCT FROM previous_set.id THEN
    RAISE EXCEPTION 'precise previous set mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='precise_citations_citationanchor' THEN
  IF NEW.ordinal>s.count OR NEW.provider_id<>s.provider_id OR NEW.subject_id<>s.subject_id OR NEW.auth_epoch<>s.auth_epoch
   OR NEW."end">char_length(a.text) OR substring(a.text FROM NEW.start+1 FOR NEW."end"-NEW.start)<>NEW.phrase
   OR NEW.phrase='' OR char_length(NEW.phrase)>2000
   OR jsonb_typeof(NEW.source) IS DISTINCT FROM 'object' OR
      NOT NEW.source ?& ARRAY['kind','id','case_id','digest','number','part_id','locator','external']
   OR (SELECT count(*) FROM jsonb_object_keys(NEW.source))<>8
   OR NEW.source->>'digest' !~ '^[a-f0-9]{64}$'
   OR NEW.source->>'number' !~ '^[1-9][0-9]{0,6}$'
   OR jsonb_typeof(NEW.source->'locator') IS DISTINCT FROM 'object'
   OR NOT (NEW.source->'locator') ?& ARRAY['mode','start','end','label','limitation']
   OR NEW.source->'locator'->>'mode' NOT IN ('TEXT','PAGE','TIME','METADATA')
  THEN RAISE EXCEPTION 'precise anchor invalid' USING ERRCODE='23514'; END IF;
  IF NEW.previous_id IS NOT NULL THEN
   SELECT * INTO previous_anchor FROM precise_citations_citationanchor WHERE id=NEW.previous_id;
   IF previous_anchor.citation_set_id IS DISTINCT FROM s.previous_id OR btrim(NEW.correction_reason)=''
   THEN RAISE EXCEPTION 'precise correction lineage invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.correction_reason<>'' THEN
   RAISE EXCEPTION 'precise correction predecessor required' USING ERRCODE='23514';
  END IF;
  source_kind:=NEW.source->>'kind'; source_id:=NEW.source->>'id'; ok:=false;
  IF source_kind='LIBRARY' THEN
   SELECT EXISTS(SELECT 1 FROM research_library_libraryversion v JOIN research_library_libraryitem i ON i.id=v.item_id
    WHERE v.id::text=source_id AND i.case_id=NEW.source_case_id AND i.case_id::text=NEW.source->>'case_id'
      AND v.digest=NEW.source->>'digest' AND v.number=(NEW.source->>'number')::integer AND NEW.source->>'part_id'='') INTO ok;
  ELSIF source_kind='ANSWER' THEN
   SELECT r.* INTO target FROM casework_answerrevision r JOIN casework_casedecision d ON d.answer_id=r.id
    WHERE r.id::text=source_id AND r.case_id=NEW.source_case_id AND r.case_id::text=NEW.source->>'case_id'
      AND r.revision=(NEW.source->>'number')::integer AND r.created_at<a.created_at AND d.action='APPROVE';
   IF target.id IS NOT NULL THEN
    IF NEW.source->>'part_id'='' THEN ok:=target.text_sha256=NEW.source->>'digest';
    ELSE SELECT EXISTS(SELECT 1 FROM answer_media_answerpart p JOIN answer_media_answermanifest m ON m.answer_id=p.manifest_id
      WHERE p.id::text=NEW.source->>'part_id' AND m.answer_id=target.id AND p.sha256=NEW.source->>'digest') INTO ok;
    END IF;
   END IF;
  ELSIF source_kind='EXTERNAL' THEN
   ok:=NEW.source_case_id IS NULL AND NEW.source->>'case_id'='' AND source_id=''
     AND NEW.source->>'part_id'='' AND NEW.source->'locator'->>'mode'='METADATA'
     AND jsonb_typeof(NEW.source->'external')='object'
     AND (NEW.source->'external') ?& ARRAY['title','edition','location','url','limitation'];
  END IF;
  IF NOT ok THEN RAISE EXCEPTION 'precise source identity invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.content_digest<>s.digest OR (NEW.provider_id=s.provider_id AND NEW.subject_id=s.subject_id)
    OR btrim(NEW.note)='' OR char_length(NEW.note)>2000 THEN
   RAISE EXCEPTION 'precise independent review invalid' USING ERRCODE='23514'; END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER precise_set_guard BEFORE INSERT OR UPDATE OR DELETE ON precise_citations_citationset FOR EACH ROW EXECUTE FUNCTION precise_history_guard();
CREATE TRIGGER precise_anchor_guard BEFORE INSERT OR UPDATE OR DELETE ON precise_citations_citationanchor FOR EACH ROW EXECUTE FUNCTION precise_history_guard();
CREATE TRIGGER precise_review_guard BEFORE INSERT OR UPDATE OR DELETE ON precise_citations_citationreview FOR EACH ROW EXECUTE FUNCTION precise_history_guard();
CREATE FUNCTION precise_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM precise_citations_citationanchor WHERE citation_set_id=NEW.id)<>NEW.count
 THEN RAISE EXCEPTION 'precise citation set incomplete' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER precise_complete AFTER INSERT ON precise_citations_citationset DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION precise_complete();
"""

REVERSE = """
DROP TRIGGER precise_complete ON precise_citations_citationset;
DROP FUNCTION precise_complete();
DROP TRIGGER precise_review_guard ON precise_citations_citationreview;
DROP TRIGGER precise_anchor_guard ON precise_citations_citationanchor;
DROP TRIGGER precise_set_guard ON precise_citations_citationset;
DROP FUNCTION precise_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("precise_citations", "0001_initial"), ("research_library", "0002_integrity")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
