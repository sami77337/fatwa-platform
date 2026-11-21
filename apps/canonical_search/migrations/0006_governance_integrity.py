from django.db import migrations

SQL = r"""
CREATE FUNCTION cs_governance_result_valid(payload jsonb, generation uuid, owner_case uuid)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE item jsonb; source record;
BEGIN
 IF jsonb_typeof(payload) IS DISTINCT FROM 'object'
 OR NOT (payload ?& ARRAY['total','limited','window','rows'])
 OR (payload-ARRAY['total','limited','window','rows'])<>'{}'::jsonb
 OR jsonb_typeof(payload->'total') IS DISTINCT FROM 'number'
 OR (payload->>'total' ~ '^[0-9]+$') IS NOT TRUE
 OR (payload->>'total')::integer NOT BETWEEN 0 AND 160
 OR jsonb_typeof(payload->'limited') IS DISTINCT FROM 'boolean'
 OR payload->'window' IS DISTINCT FROM '20'::jsonb
 OR jsonb_typeof(payload->'rows') IS DISTINCT FROM 'array'
 THEN RETURN false; END IF;
 IF jsonb_array_length(payload->'rows')>20
 OR jsonb_array_length(payload->'rows')>(payload->>'total')::integer
 OR (SELECT count(DISTINCT r->>'document_id') FROM jsonb_array_elements(payload->'rows') r)
    <>jsonb_array_length(payload->'rows')
 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(payload->'rows') LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'object'
   OR NOT(item ?& ARRAY['document_id','generation_id','case_id','kind','pin'])
   OR (item-ARRAY['document_id','generation_id','case_id','kind','pin'])<>'{}'::jsonb
   OR item->>'generation_id' IS DISTINCT FROM generation::text
   OR item->>'case_id' IS DISTINCT FROM owner_case::text
   THEN RETURN false; END IF;
   SELECT * INTO source FROM canonical_search_searchdocument
   WHERE id::text=item->>'document_id' AND generation_id=generation;
   IF source.id IS NULL OR source.kind IS DISTINCT FROM item->>'kind'
   OR source.pin IS DISTINCT FROM item->'pin' THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION cs_governance_difference(before_value jsonb, after_value jsonb)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH old_rows AS (
   SELECT value->>'document_id' AS identifier, n FROM jsonb_array_elements(before_value->'rows')
   WITH ORDINALITY AS rows(value,n)
 ), new_rows AS (
   SELECT value->>'document_id' AS identifier, n FROM jsonb_array_elements(after_value->'rows')
   WITH ORDINALITY AS rows(value,n)
 )
 SELECT jsonb_build_object(
   'added',coalesce((SELECT jsonb_agg(identifier ORDER BY n) FROM new_rows
                     WHERE identifier NOT IN (SELECT identifier FROM old_rows)),'[]'::jsonb),
   'removed',coalesce((SELECT jsonb_agg(identifier ORDER BY n) FROM old_rows
                     WHERE identifier NOT IN (SELECT identifier FROM new_rows)),'[]'::jsonb),
   'baseline_order',coalesce((SELECT jsonb_agg(identifier ORDER BY n) FROM old_rows),'[]'::jsonb),
   'candidate_order',coalesce((SELECT jsonb_agg(identifier ORDER BY n) FROM new_rows),'[]'::jsonb),
   'window',20)
$$;

CREATE FUNCTION cs_governance_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c record; previous record; revision record; preview record; approval record;
        g record; entry jsonb; item jsonb; target jsonb; old_keys text[]; new_keys text[];
        used_keys text[]; mapped_keys text[]; pin jsonb; samples jsonb; source_pin jsonb;
BEGIN
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF c.id IS NULL OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR length(NEW.subject_id)>128 OR length(NEW.provider_id)>128 OR length(NEW.auth_epoch)>64
 OR octet_length(NEW.canonical_payload)>1048576
 OR (TG_TABLE_NAME<>'canonical_search_synonymdecision' AND NEW.canonical_payload::jsonb IS DISTINCT FROM
    to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'])
 OR (TG_TABLE_NAME='canonical_search_synonymdecision' AND (NEW.canonical_payload::jsonb-'valid_until') IS DISTINCT FROM
    to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at','valid_until'])
 OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')<>NEW.digest
 THEN RAISE EXCEPTION 'invalid governed search identity or canonical record' USING ERRCODE='23514'; END IF;

 IF TG_TABLE_NAME='canonical_search_synonymrevision' THEN
   SELECT * INTO previous FROM canonical_search_synonymrevision
   WHERE case_id=NEW.case_id ORDER BY number DESC LIMIT 1;
   IF NEW.number<>coalesce(previous.number,0)+1
   OR NEW.previous_id IS DISTINCT FROM previous.id
   OR length(btrim(NEW.title)) NOT BETWEEN 1 AND 160
   OR length(btrim(NEW.provenance)) NOT BETWEEN 1 AND 1000
   OR NEW.profile<>'ar-simple-trigram-dev-v1'
   OR jsonb_typeof(NEW.entries) IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.entries) NOT BETWEEN 1 AND 12
   OR jsonb_typeof(NEW.mapping) IS DISTINCT FROM 'array'
   OR octet_length(NEW.entries::text)>20000 OR octet_length(NEW.mapping::text)>20000
   THEN RAISE EXCEPTION 'invalid synonym version or entries' USING ERRCODE='23514'; END IF;
   new_keys:=ARRAY[]::text[];
   FOR entry IN SELECT value FROM jsonb_array_elements(NEW.entries) LOOP
     IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
     OR NOT (entry ?& ARRAY['key','term','alternatives'])
     OR (entry-ARRAY['key','term','alternatives'])<>'{}'::jsonb
     OR (entry->>'key' ~ '^[a-z][a-z0-9._-]{0,39}$') IS NOT TRUE
     OR jsonb_typeof(entry->'term') IS DISTINCT FROM 'string'
     OR length(btrim(entry->>'term')) NOT BETWEEN 1 AND 48
     OR jsonb_typeof(entry->'alternatives') IS DISTINCT FROM 'array'
     OR jsonb_array_length(entry->'alternatives') NOT BETWEEN 1 AND 3
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(entry->'alternatives') a
               WHERE jsonb_typeof(a) IS DISTINCT FROM 'string'
               OR length(btrim(a#>>'{}')) NOT BETWEEN 1 AND 48)
     OR (SELECT count(DISTINCT a) FROM jsonb_array_elements(entry->'alternatives') a)
        <>jsonb_array_length(entry->'alternatives')
     OR entry->>'key'=ANY(new_keys)
     THEN RAISE EXCEPTION 'invalid synonym term and alternatives' USING ERRCODE='23514'; END IF;
     new_keys:=array_append(new_keys,entry->>'key');
   END LOOP;
   old_keys:=ARRAY(SELECT value->>'key' FROM jsonb_array_elements(coalesce(previous.entries,'[]'::jsonb)));
   used_keys:=ARRAY(SELECT DISTINCT e->>'key' FROM canonical_search_synonymrevision r,
                     LATERAL jsonb_array_elements(r.entries) e WHERE r.case_id=NEW.case_id);
   IF EXISTS(SELECT 1 FROM unnest(new_keys) k WHERE k=ANY(used_keys) AND NOT k=ANY(old_keys))
   OR jsonb_array_length(NEW.mapping)<>cardinality(old_keys)
   THEN RAISE EXCEPTION 'synonym historical identifiers require explicit mapping' USING ERRCODE='23514'; END IF;
   mapped_keys:=ARRAY[]::text[];
   FOR item IN SELECT value FROM jsonb_array_elements(NEW.mapping) LOOP
     IF jsonb_typeof(item) IS DISTINCT FROM 'object'
     OR NOT (item ?& ARRAY['from','kind','to','reason'])
     OR (item-ARRAY['from','kind','to','reason'])<>'{}'::jsonb
     OR NOT coalesce(item->>'from'=ANY(old_keys),false) OR item->>'from'=ANY(mapped_keys)
     OR coalesce(item->>'kind','') NOT IN ('SAME','RENAMED','MOVED','SPLIT','MERGED','NO_EQUIVALENT')
     OR jsonb_typeof(item->'reason') IS DISTINCT FROM 'string'
     OR length(btrim(item->>'reason')) NOT BETWEEN 1 AND 500
     OR jsonb_typeof(item->'to') IS DISTINCT FROM 'array'
     THEN RAISE EXCEPTION 'invalid synonym mapping' USING ERRCODE='23514'; END IF;
     IF (item->>'kind'='NO_EQUIVALENT' AND jsonb_array_length(item->'to')<>0)
     OR (item->>'kind'='SPLIT' AND jsonb_array_length(item->'to') NOT BETWEEN 2 AND 12)
     OR (item->>'kind' NOT IN ('NO_EQUIVALENT','SPLIT') AND jsonb_array_length(item->'to')<>1)
     OR (SELECT count(DISTINCT a) FROM jsonb_array_elements(item->'to') a)<>jsonb_array_length(item->'to')
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(item->'to') a
               WHERE jsonb_typeof(a) IS DISTINCT FROM 'string' OR NOT (a#>>'{}')=ANY(new_keys))
     THEN RAISE EXCEPTION 'invalid synonym mapping targets' USING ERRCODE='23514'; END IF;
     IF item->>'kind'='SAME' AND (
        item->'to' IS DISTINCT FROM jsonb_build_array(item->>'from')
        OR (SELECT value->>'term' FROM jsonb_array_elements(previous.entries) WHERE value->>'key'=item->>'from')
        IS DISTINCT FROM (SELECT value->>'term' FROM jsonb_array_elements(NEW.entries) WHERE value->>'key'=item->>'from'))
     THEN RAISE EXCEPTION 'same synonym identifier changed' USING ERRCODE='23514'; END IF;
     IF item->>'kind'='MERGED' AND
       (SELECT count(*) FROM jsonb_array_elements(NEW.mapping) m
        WHERE m->>'kind'='MERGED' AND m->'to'=item->'to')<2
     THEN RAISE EXCEPTION 'synonym merge must map multiple source identifiers' USING ERRCODE='23514'; END IF;
     mapped_keys:=array_append(mapped_keys,item->>'from');
   END LOOP;
 ELSE
   SELECT * INTO revision FROM canonical_search_synonymrevision WHERE id=NEW.revision_id;
   IF revision.id IS NULL OR revision.case_id<>NEW.case_id
   THEN RAISE EXCEPTION 'governed search revision case mismatch' USING ERRCODE='23514'; END IF;

   IF TG_TABLE_NAME='canonical_search_synonymdecision' THEN
     IF NOT (NEW.canonical_payload::jsonb ? 'valid_until')
     OR (NEW.canonical_payload::jsonb->>'valid_until')::timestamptz IS DISTINCT FROM NEW.valid_until
     THEN RAISE EXCEPTION 'synonym expiry differs from canonical timestamp' USING ERRCODE='23514'; END IF;
     SELECT * INTO previous FROM canonical_search_synonymdecision
     WHERE revision_id=NEW.revision_id ORDER BY sequence DESC LIMIT 1;
     IF NEW.sequence<>coalesce(previous.sequence,0)+1 OR length(btrim(NEW.note)) NOT BETWEEN 1 AND 2000
     THEN RAISE EXCEPTION 'invalid synonym review sequence or note' USING ERRCODE='23514'; END IF;
     IF NEW.action='RETIRE' THEN
       IF previous.action IS DISTINCT FROM 'APPROVE' OR NEW.preview_id IS NOT NULL
       OR NEW.valid_until IS NOT NULL OR NEW.ttl_minutes<>0 OR NEW.sequence<>2
       THEN RAISE EXCEPTION 'invalid synonym retirement' USING ERRCODE='23514'; END IF;
     ELSE
       SELECT * INTO preview FROM canonical_search_synonympreview WHERE id=NEW.preview_id;
       IF previous.id IS NOT NULL OR preview.id IS NULL OR preview.revision_id<>revision.id
       OR preview.case_id<>NEW.case_id
       OR (NEW.provider_id=revision.provider_id AND NEW.subject_id=revision.subject_id)
       OR (NEW.provider_id=preview.provider_id AND NEW.subject_id=preview.subject_id)
       OR (NEW.action='APPROVE' AND (NEW.ttl_minutes NOT BETWEEN 1 AND 1440
           OR NEW.valid_until IS NULL OR NEW.valid_until<=clock_timestamp()
           OR NEW.valid_until>clock_timestamp()+make_interval(mins=>NEW.ttl_minutes)+interval '1 second'))
       OR (NEW.action='REJECT' AND (NEW.ttl_minutes<>0 OR NEW.valid_until IS NOT NULL))
       THEN RAISE EXCEPTION 'synonym review needs independent author and exact preview' USING ERRCODE='23514'; END IF;
       source_pin:=preview.source_pin;
     END IF;
   ELSIF TG_TABLE_NAME='canonical_search_synonympreview' THEN
     IF (SELECT count(*) FROM canonical_search_synonympreview WHERE revision_id=revision.id)>=16
     OR jsonb_typeof(NEW.queries) IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.queries) NOT BETWEEN 1 AND 8
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.queries) q
               WHERE jsonb_typeof(q) IS DISTINCT FROM 'string' OR length(btrim(q#>>'{}')) NOT BETWEEN 1 AND 120)
     OR (SELECT count(DISTINCT q) FROM jsonb_array_elements(NEW.queries) q)<>jsonb_array_length(NEW.queries)
     OR jsonb_typeof(NEW.impact) IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.impact)<>jsonb_array_length(NEW.queries)
     OR octet_length(NEW.impact::text)>524288
     THEN RAISE EXCEPTION 'invalid bounded synonym preview' USING ERRCODE='23514'; END IF;
     source_pin:=NEW.source_pin;
   ELSIF TG_TABLE_NAME='canonical_search_shadowcomparison' THEN
     SELECT * INTO approval FROM canonical_search_synonymdecision
     WHERE revision_id=revision.id ORDER BY sequence DESC LIMIT 1;
     IF approval.id IS DISTINCT FROM NEW.approval_id OR approval.action IS DISTINCT FROM 'APPROVE'
     OR approval.valid_until<=clock_timestamp()
     OR (SELECT count(*) FROM canonical_search_shadowcomparison WHERE case_id=NEW.case_id)>=128
     OR length(btrim(NEW.query)) NOT BETWEEN 1 AND 120
     OR NEW.baseline_profile<>'ar-simple-trigram-dev-v1'
     OR NEW.candidate_profile<>NEW.baseline_profile||':'||revision.digest
     OR NEW.baseline_ms NOT BETWEEN 0 AND 3600000 OR NEW.candidate_ms NOT BETWEEN 0 AND 3600000
     OR octet_length(NEW.baseline::text)+octet_length(NEW.candidate::text)>131072
     THEN RAISE EXCEPTION 'invalid current shadow candidate' USING ERRCODE='23514'; END IF;
     source_pin:=NEW.source_pin;
   ELSE
     RAISE EXCEPTION 'unknown governed search table' USING ERRCODE='23514';
   END IF;

   IF source_pin IS NOT NULL THEN
     IF jsonb_typeof(source_pin) IS DISTINCT FROM 'object'
     OR NOT (source_pin ?& ARRAY['case_id','generation_id','generation_digest','source_fingerprint','allowed_fingerprint'])
     OR (source_pin-ARRAY['case_id','generation_id','generation_digest','source_fingerprint','allowed_fingerprint'])<>'{}'::jsonb
     OR source_pin->>'case_id' IS DISTINCT FROM NEW.case_id::text
     OR (source_pin->>'allowed_fingerprint' ~ '^[a-f0-9]{64}$') IS NOT TRUE
     THEN RAISE EXCEPTION 'invalid governed source pins' USING ERRCODE='23514'; END IF;
     SELECT * INTO g FROM canonical_search_searchgeneration WHERE case_id=NEW.case_id ORDER BY number DESC LIMIT 1;
     IF g.id IS NULL OR g.id::text IS DISTINCT FROM source_pin->>'generation_id'
     OR g.digest IS DISTINCT FROM source_pin->>'generation_digest'
     OR g.source_fingerprint IS DISTINCT FROM source_pin->>'source_fingerprint'
     OR g.case_revision<>c.revision OR g.evidence_version<>c.evidence_version
     THEN RAISE EXCEPTION 'governed source generation is stale' USING ERRCODE='23514'; END IF;
   END IF;
   IF TG_TABLE_NAME='canonical_search_synonympreview' THEN
     FOR item IN SELECT value FROM jsonb_array_elements(NEW.impact) WITH ORDINALITY AS rows(value,n) LOOP
       IF jsonb_typeof(item) IS DISTINCT FROM 'object'
       OR NOT(item ?& ARRAY['query','baseline','candidate','difference'])
       OR (item-ARRAY['query','baseline','candidate','difference'])<>'{}'::jsonb
       OR NOT NEW.queries @> jsonb_build_array(item->>'query')
       OR cs_governance_result_valid(item->'baseline',g.id,NEW.case_id) IS NOT TRUE
       OR cs_governance_result_valid(item->'candidate',g.id,NEW.case_id) IS NOT TRUE
       OR item->'difference' IS DISTINCT FROM cs_governance_difference(item->'baseline',item->'candidate')
       THEN RAISE EXCEPTION 'preview results lack exact canonical pins' USING ERRCODE='23514'; END IF;
     END LOOP;
     IF ARRAY(SELECT value->>'query' FROM jsonb_array_elements(NEW.impact))
        IS DISTINCT FROM ARRAY(SELECT value#>>'{}' FROM jsonb_array_elements(NEW.queries))
     THEN RAISE EXCEPTION 'preview query sequence differs' USING ERRCODE='23514'; END IF;
   ELSIF TG_TABLE_NAME='canonical_search_shadowcomparison' THEN
     IF cs_governance_result_valid(NEW.baseline,g.id,NEW.case_id) IS NOT TRUE
     OR (NEW.candidate_status='OK' AND (cs_governance_result_valid(NEW.candidate,g.id,NEW.case_id) IS NOT TRUE
         OR NEW.difference IS DISTINCT FROM cs_governance_difference(NEW.baseline,NEW.candidate)))
     OR (NEW.candidate_status='ERROR' AND (NEW.candidate<>'{}'::jsonb OR NEW.difference<>'{}'::jsonb))
     THEN RAISE EXCEPTION 'shadow results lack exact canonical pins' USING ERRCODE='23514'; END IF;
   END IF;
 END IF;
 NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE TRIGGER cs_synonym_insert BEFORE INSERT ON canonical_search_synonymrevision
 FOR EACH ROW EXECUTE FUNCTION cs_governance_insert();
CREATE TRIGGER cs_synonym_immutable BEFORE UPDATE OR DELETE ON canonical_search_synonymrevision
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
CREATE TRIGGER cs_preview_insert BEFORE INSERT ON canonical_search_synonympreview
 FOR EACH ROW EXECUTE FUNCTION cs_governance_insert();
CREATE TRIGGER cs_preview_immutable BEFORE UPDATE OR DELETE ON canonical_search_synonympreview
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
CREATE TRIGGER cs_decision_insert BEFORE INSERT ON canonical_search_synonymdecision
 FOR EACH ROW EXECUTE FUNCTION cs_governance_insert();
CREATE TRIGGER cs_decision_immutable BEFORE UPDATE OR DELETE ON canonical_search_synonymdecision
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
CREATE TRIGGER cs_shadow_insert BEFORE INSERT ON canonical_search_shadowcomparison
 FOR EACH ROW EXECUTE FUNCTION cs_governance_insert();
CREATE TRIGGER cs_shadow_immutable BEFORE UPDATE OR DELETE ON canonical_search_shadowcomparison
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
"""

REVERSE = """
DROP TRIGGER cs_synonym_insert ON canonical_search_synonymrevision;
DROP TRIGGER cs_synonym_immutable ON canonical_search_synonymrevision;
DROP TRIGGER cs_preview_insert ON canonical_search_synonympreview;
DROP TRIGGER cs_preview_immutable ON canonical_search_synonympreview;
DROP TRIGGER cs_decision_insert ON canonical_search_synonymdecision;
DROP TRIGGER cs_decision_immutable ON canonical_search_synonymdecision;
DROP TRIGGER cs_shadow_insert ON canonical_search_shadowcomparison;
DROP TRIGGER cs_shadow_immutable ON canonical_search_shadowcomparison;
DROP FUNCTION cs_governance_insert();
DROP FUNCTION cs_governance_difference(jsonb,jsonb);
DROP FUNCTION cs_governance_result_valid(jsonb,uuid,uuid);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("canonical_search", "0005_synonymrevision_synonympreview_synonymdecision_and_more"),
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
