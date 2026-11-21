from django.db import migrations

SQL = r"""
CREATE FUNCTION development_taxonomy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE t development_taxonomy_developmenttree%ROWTYPE; v development_taxonomy_treeversion%ROWTYPE;
 oldv development_taxonomy_treeversion%ROWTYPE; targetv development_taxonomy_treeversion%ROWTYPE;
 b development_taxonomy_caseclassification%ROWTYPE; prev development_taxonomy_caseclassification%ROWTYPE;
 p development_taxonomy_migrationplan%ROWTYPE; x development_taxonomy_migrationexecution%ROWTYPE;
 review_row development_taxonomy_humanreview%ROWTYPE; c casework_case%ROWTYPE;
 item jsonb; mapped jsonb; before_data jsonb; chosen jsonb; oldnode jsonb; newnode jsonb;
 current_id text; parent_id text; seen text[]; ids text[]; old_ids text[]; new_ids text[];
 targets text[]; selection text[]; source_key text; entry record; expected integer; n integer;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'taxonomy history immutable' USING ERRCODE='23514'; END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
 THEN RAISE EXCEPTION 'taxonomy seal invalid' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 IF TG_TABLE_NAME='development_taxonomy_developmenttree' THEN
  IF btrim(NEW.title)='' OR btrim(NEW.provenance)='' THEN RAISE EXCEPTION 'provisional tree provenance required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='development_taxonomy_concept' THEN
  IF btrim(NEW.definition)='' THEN RAISE EXCEPTION 'stable concept definition required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='development_taxonomy_treeversion' THEN
  SELECT * INTO oldv FROM development_taxonomy_treeversion WHERE tree_id=NEW.tree_id ORDER BY number DESC LIMIT 1;
  IF NEW.number<>coalesce(oldv.number,0)+1 OR NEW.previous_id IS DISTINCT FROM oldv.id
   OR jsonb_typeof(NEW.nodes) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.nodes) NOT BETWEEN 1 AND 64 OR btrim(NEW.reason)=''
  THEN RAISE EXCEPTION 'taxonomy version invalid' USING ERRCODE='23514'; END IF;
  ids:=ARRAY(SELECT value->>'id' FROM jsonb_array_elements(NEW.nodes));
  IF (SELECT count(DISTINCT entry_value.value) FROM unnest(ids) AS entry_value(value))<>cardinality(ids) THEN RAISE EXCEPTION 'taxonomy duplicate node' USING ERRCODE='23514'; END IF;
  FOR entry IN SELECT value, ordinality FROM jsonb_array_elements(NEW.nodes) WITH ORDINALITY LOOP
   item:=entry.value;
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR NOT item ?& ARRAY['id','parent','name','order']
    OR (SELECT count(*) FROM jsonb_object_keys(item))<>4 OR jsonb_typeof(item->'id')<>'string'
    OR jsonb_typeof(item->'name')<>'string' OR char_length(btrim(item->>'name')) NOT BETWEEN 1 AND 160
    OR (item->>'order')::integer<>entry.ordinality
    OR NOT EXISTS(SELECT 1 FROM development_taxonomy_concept WHERE id=(item->>'id')::uuid AND tree_id=NEW.tree_id)
   THEN RAISE EXCEPTION 'taxonomy node invalid' USING ERRCODE='23514'; END IF;
   seen:=ARRAY[]::text[]; current_id:=item->>'id';
   WHILE current_id IS NOT NULL LOOP
    IF current_id=ANY(seen) OR NOT current_id=ANY(ids) OR cardinality(seen)>=8 THEN RAISE EXCEPTION 'taxonomy cycle or depth' USING ERRCODE='23514'; END IF;
    seen:=array_append(seen,current_id);
    SELECT value->>'parent' INTO current_id FROM jsonb_array_elements(NEW.nodes) WHERE value->>'id'=current_id;
   END LOOP;
  END LOOP;
 ELSIF TG_TABLE_NAME='development_taxonomy_humanreview' THEN
  IF NEW.version_id IS NOT NULL THEN
   SELECT * INTO v FROM development_taxonomy_treeversion WHERE id=NEW.version_id;
   IF EXISTS(SELECT 1 FROM development_taxonomy_treeversion WHERE tree_id=v.tree_id AND number>v.number)
   THEN RAISE EXCEPTION 'latest taxonomy version required' USING ERRCODE='23514'; END IF;
   current_id:=v.digest; parent_id:=v.provider_id; source_key:=v.subject_id;
  ELSE
   SELECT * INTO p FROM development_taxonomy_migrationplan WHERE id=NEW.plan_id;
   current_id:=p.digest; parent_id:=p.provider_id; source_key:=p.subject_id;
  END IF;
  IF current_id IS NULL OR NEW.content_digest<>current_id OR (NEW.provider_id=parent_id AND NEW.subject_id=source_key) OR btrim(NEW.reason)=''
  THEN RAISE EXCEPTION 'independent taxonomy review required' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='development_taxonomy_migrationplan' THEN
  SELECT * INTO oldv FROM development_taxonomy_treeversion WHERE id=NEW.source_version_id;
  SELECT * INTO targetv FROM development_taxonomy_treeversion WHERE id=NEW.target_version_id;
  IF oldv.tree_id<>NEW.tree_id OR targetv.tree_id<>NEW.tree_id OR oldv.number>=targetv.number
   OR NOT EXISTS(SELECT 1 FROM development_taxonomy_humanreview WHERE version_id=oldv.id AND action='APPROVE' AND content_digest=oldv.digest)
   OR NOT EXISTS(SELECT 1 FROM development_taxonomy_humanreview WHERE version_id=targetv.id AND action='APPROVE' AND content_digest=targetv.digest)
   OR jsonb_typeof(NEW.mapping) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.mapping)<>jsonb_array_length(oldv.nodes)
   OR jsonb_typeof(NEW.manifest) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.manifest)>32 OR btrim(NEW.reason)=''
  THEN RAISE EXCEPTION 'reviewed taxonomy versions required' USING ERRCODE='23514'; END IF;
  old_ids:=ARRAY(SELECT value->>'id' FROM jsonb_array_elements(oldv.nodes));
  new_ids:=ARRAY(SELECT value->>'id' FROM jsonb_array_elements(targetv.nodes));
  IF (SELECT count(DISTINCT value->>'source') FROM jsonb_array_elements(NEW.mapping))<>cardinality(old_ids)
  THEN RAISE EXCEPTION 'taxonomy mapping incomplete' USING ERRCODE='23514'; END IF;
  FOR mapped IN SELECT value FROM jsonb_array_elements(NEW.mapping) LOOP
   IF NOT mapped ?& ARRAY['source','kind','targets','reason'] OR (SELECT count(*) FROM jsonb_object_keys(mapped))<>4
    OR NOT (mapped->>'source')=ANY(old_ids) OR mapped->>'kind' NOT IN ('SAME','RENAMED','MOVED','SPLIT','MERGED','NO_EQUIVALENT')
    OR jsonb_typeof(mapped->'targets') IS DISTINCT FROM 'array' OR btrim(mapped->>'reason')=''
   THEN RAISE EXCEPTION 'taxonomy mapping item invalid' USING ERRCODE='23514'; END IF;
   targets:=ARRAY(SELECT jsonb_array_elements_text(mapped->'targets'));
   IF NOT targets<@new_ids OR cardinality(targets)<>(SELECT count(DISTINCT z) FROM unnest(targets) z)
   THEN RAISE EXCEPTION 'taxonomy mapping targets invalid' USING ERRCODE='23514'; END IF;
   SELECT value INTO oldnode FROM jsonb_array_elements(oldv.nodes) WHERE value->>'id'=mapped->>'source';
   SELECT value INTO newnode FROM jsonb_array_elements(targetv.nodes) WHERE value->>'id'=mapped->>'source';
   IF mapped->>'kind' IN ('SAME','RENAMED','MOVED') THEN
    IF targets IS DISTINCT FROM ARRAY[mapped->>'source'] OR newnode IS NULL
     OR (mapped->>'kind'='SAME' AND oldnode IS DISTINCT FROM newnode)
     OR (mapped->>'kind'='RENAMED' AND oldnode->>'name'=newnode->>'name')
     OR (mapped->>'kind'='MOVED' AND (oldnode->'parent',oldnode->'order') IS NOT DISTINCT FROM (newnode->'parent',newnode->'order'))
    THEN RAISE EXCEPTION 'taxonomy stable mapping mismatch' USING ERRCODE='23514'; END IF;
   ELSIF mapped->>'kind'='NO_EQUIVALENT' THEN
    IF cardinality(targets)<>0 OR newnode IS NOT NULL THEN RAISE EXCEPTION 'taxonomy unavailable equivalent mismatch' USING ERRCODE='23514'; END IF;
   ELSE
    IF newnode IS NOT NULL OR targets&&old_ids OR (mapped->>'kind'='SPLIT' AND cardinality(targets)<2)
     OR (mapped->>'kind'='MERGED' AND (cardinality(targets)<>1 OR (SELECT count(*) FROM jsonb_array_elements(NEW.mapping) z WHERE z->>'kind'='MERGED' AND z->'targets'=mapped->'targets')<2))
    THEN RAISE EXCEPTION 'new taxonomy meaning requires new identity' USING ERRCODE='23514'; END IF;
   END IF;
  END LOOP;
  IF (SELECT count(DISTINCT value->>'case_id') FROM jsonb_array_elements(NEW.manifest))<>jsonb_array_length(NEW.manifest)
  THEN RAISE EXCEPTION 'taxonomy duplicate case' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM development_taxonomy_caseclassification z WHERE z.version_id=oldv.id
       AND NOT EXISTS(SELECT 1 FROM development_taxonomy_caseclassification later WHERE later.case_id=z.case_id AND later.sequence>z.sequence))<>jsonb_array_length(NEW.manifest)
  THEN RAISE EXCEPTION 'taxonomy complete impact set required' USING ERRCODE='23514'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(NEW.manifest) ORDER BY value->>'case_id' LOOP
   IF NOT item ?& ARRAY['case_id','case_ref','case_revision','evidence_version','answer_id','before_id','before_digest','before','after','resolution_reason']
    OR (SELECT count(*) FROM jsonb_object_keys(item))<>10 OR btrim(item->>'resolution_reason')=''
   THEN RAISE EXCEPTION 'taxonomy impact invalid' USING ERRCODE='23514'; END IF;
   SELECT * INTO c FROM casework_case WHERE id=(item->>'case_id')::uuid FOR UPDATE;
   SELECT * INTO b FROM development_taxonomy_caseclassification WHERE case_id=c.id ORDER BY sequence DESC LIMIT 1;
   IF b.id IS NULL OR b.id::text<>item->>'before_id' OR b.digest<>item->>'before_digest' OR b.version_id<>oldv.id
    OR c.revision<>(item->>'case_revision')::integer OR c.evidence_version<>(item->>'evidence_version')::integer OR c.approved_answer_id::text IS DISTINCT FROM item->>'answer_id'
    OR c.public_ref<>item->>'case_ref' OR b.answer_id IS DISTINCT FROM c.approved_answer_id
    OR item->'before' IS DISTINCT FROM jsonb_build_object('version_id',oldv.id::text,'primary',b.primary_id::text,'additional',b.additional)
   THEN RAISE EXCEPTION 'taxonomy impact changed' USING ERRCODE='23514'; END IF;
   IF item->'after'<>'null'::jsonb THEN
    chosen:=item->'after';
    IF jsonb_typeof(chosen) IS DISTINCT FROM 'object' OR NOT chosen ?& ARRAY['version_id','primary','additional'] OR (SELECT count(*) FROM jsonb_object_keys(chosen))<>3
     OR chosen->>'version_id'<>targetv.id::text OR jsonb_typeof(chosen->'additional') IS DISTINCT FROM 'array'
    THEN RAISE EXCEPTION 'taxonomy resolved impact invalid' USING ERRCODE='23514'; END IF;
    selection:=ARRAY[chosen->>'primary']||ARRAY(SELECT jsonb_array_elements_text(chosen->'additional'));
    targets:=ARRAY[]::text[];
    FOR source_key IN SELECT b.primary_id::text UNION ALL SELECT jsonb_array_elements_text(b.additional) LOOP
     SELECT value INTO mapped FROM jsonb_array_elements(NEW.mapping) WHERE value->>'source'=source_key;
     ids:=ARRAY(SELECT jsonb_array_elements_text(mapped->'targets'));
     IF cardinality(ids)=0 OR NOT selection&&ids THEN RAISE EXCEPTION 'unresolved taxonomy impact must remain held' USING ERRCODE='23514'; END IF;
     targets:=targets||ids;
    END LOOP;
    IF NOT selection<@targets THEN RAISE EXCEPTION 'taxonomy unrelated target selection' USING ERRCODE='23514'; END IF;
   END IF;
  END LOOP;
 ELSIF TG_TABLE_NAME='development_taxonomy_migrationexecution' THEN
  SELECT * INTO p FROM development_taxonomy_migrationplan WHERE id=NEW.plan_id;
  IF NOT EXISTS(SELECT 1 FROM development_taxonomy_humanreview WHERE plan_id=p.id AND action='APPROVE' AND content_digest=p.digest)
   OR NEW.count<>(SELECT count(*) FROM jsonb_array_elements(p.manifest) z WHERE z->'after'<>'null'::jsonb) OR btrim(NEW.reason)=''
  THEN RAISE EXCEPTION 'reviewed complete migration required' USING ERRCODE='23514'; END IF;
  IF NEW.kind='ROLLBACK' THEN
   SELECT * INTO x FROM development_taxonomy_migrationexecution WHERE id=NEW.previous_id;
   IF x.id IS NULL OR x.plan_id<>NEW.plan_id OR x.kind<>'APPLY' THEN RAISE EXCEPTION 'exact migration rollback required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.previous_id IS NOT NULL THEN RAISE EXCEPTION 'unexpected previous migration' USING ERRCODE='23514'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(p.manifest) ORDER BY value->>'case_id' LOOP
   SELECT * INTO c FROM casework_case WHERE id=(item->>'case_id')::uuid FOR UPDATE;
   SELECT * INTO b FROM development_taxonomy_caseclassification WHERE case_id=c.id ORDER BY sequence DESC LIMIT 1;
   IF c.revision<>(item->>'case_revision')::integer OR c.evidence_version<>(item->>'evidence_version')::integer OR c.approved_answer_id::text IS DISTINCT FROM item->>'answer_id'
   THEN RAISE EXCEPTION 'migration canonical case changed' USING ERRCODE='23514'; END IF;
   IF NEW.kind='ROLLBACK' AND item->'after'<>'null'::jsonb THEN
    IF b.execution_id IS DISTINCT FROM NEW.previous_id OR b.previous_id::text IS DISTINCT FROM item->>'before_id'
    THEN RAISE EXCEPTION 'rollback would overwrite newer binding' USING ERRCODE='23514'; END IF;
   ELSE
    IF b.id::text IS DISTINCT FROM item->>'before_id' OR b.digest IS DISTINCT FROM item->>'before_digest'
    THEN RAISE EXCEPTION 'migration binding changed' USING ERRCODE='23514'; END IF;
   END IF;
  END LOOP;
 ELSE
  SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
  SELECT * INTO prev FROM development_taxonomy_caseclassification WHERE case_id=NEW.case_id ORDER BY sequence DESC LIMIT 1;
  SELECT * INTO v FROM development_taxonomy_treeversion WHERE id=NEW.version_id;
  IF c.stage<>'ANSWERED' OR c.approved_answer_id IS DISTINCT FROM NEW.answer_id OR c.evidence_version<>NEW.evidence_version
   OR NEW.sequence<>coalesce(prev.sequence,0)+1 OR NEW.previous_id IS DISTINCT FROM prev.id
   OR NOT EXISTS(SELECT 1 FROM development_taxonomy_humanreview WHERE version_id=v.id AND action='APPROVE' AND content_digest=v.digest)
   OR jsonb_typeof(NEW.additional) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.additional)>12 OR btrim(NEW.reason)=''
  THEN RAISE EXCEPTION 'exact reviewed current taxonomy binding required' USING ERRCODE='23514'; END IF;
  ids:=ARRAY(SELECT value->>'id' FROM jsonb_array_elements(v.nodes));
  selection:=ARRAY[NEW.primary_id::text]||ARRAY(SELECT jsonb_array_elements_text(NEW.additional));
  IF NOT selection<@ids OR cardinality(selection)<>(SELECT count(DISTINCT z) FROM unnest(selection) z)
  THEN RAISE EXCEPTION 'taxonomy primary additional selection invalid' USING ERRCODE='23514'; END IF;
  IF NEW.execution_id IS NOT NULL THEN
   SELECT * INTO x FROM development_taxonomy_migrationexecution WHERE id=NEW.execution_id;
   SELECT * INTO p FROM development_taxonomy_migrationplan WHERE id=x.plan_id;
   SELECT value INTO item FROM jsonb_array_elements(p.manifest) WHERE value->>'case_id'=NEW.case_id::text;
   chosen:=CASE WHEN x.kind='APPLY' THEN item->'after' ELSE item->'before' END;
   IF chosen IS NULL OR chosen='null'::jsonb OR chosen IS DISTINCT FROM jsonb_build_object('version_id',v.id::text,'primary',NEW.primary_id::text,'additional',NEW.additional)
    OR c.revision<>(item->>'case_revision')::integer OR NEW.answer_id::text<>item->>'answer_id'
    OR (x.kind='APPLY' AND (NEW.previous_id::text IS DISTINCT FROM item->>'before_id' OR prev.digest IS DISTINCT FROM item->>'before_digest'))
    OR (x.kind='ROLLBACK' AND (prev.execution_id IS DISTINCT FROM x.previous_id OR prev.previous_id::text IS DISTINCT FROM item->>'before_id'))
    OR NEW.provider_id<>x.provider_id OR NEW.subject_id<>x.subject_id OR NEW.auth_epoch<>x.auth_epoch
   THEN RAISE EXCEPTION 'taxonomy execution binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER dt_tree_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_developmenttree FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE TRIGGER dt_concept_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_concept FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE TRIGGER dt_version_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_treeversion FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE TRIGGER dt_review_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_humanreview FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE TRIGGER dt_plan_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_migrationplan FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE TRIGGER dt_execution_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_migrationexecution FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE TRIGGER dt_binding_guard BEFORE INSERT OR UPDATE OR DELETE ON development_taxonomy_caseclassification FOR EACH ROW EXECUTE FUNCTION development_taxonomy_guard();
CREATE FUNCTION development_taxonomy_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM development_taxonomy_caseclassification WHERE execution_id=NEW.id)<>NEW.count
 THEN RAISE EXCEPTION 'taxonomy migration incomplete' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER dt_execution_complete AFTER INSERT ON development_taxonomy_migrationexecution DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION development_taxonomy_complete();
"""

REVERSE = """
DROP TRIGGER dt_execution_complete ON development_taxonomy_migrationexecution;
DROP FUNCTION development_taxonomy_complete();
DROP TRIGGER dt_binding_guard ON development_taxonomy_caseclassification;
DROP TRIGGER dt_execution_guard ON development_taxonomy_migrationexecution;
DROP TRIGGER dt_plan_guard ON development_taxonomy_migrationplan;
DROP TRIGGER dt_review_guard ON development_taxonomy_humanreview;
DROP TRIGGER dt_version_guard ON development_taxonomy_treeversion;
DROP TRIGGER dt_concept_guard ON development_taxonomy_concept;
DROP TRIGGER dt_tree_guard ON development_taxonomy_developmenttree;
DROP FUNCTION development_taxonomy_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("development_taxonomy", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
