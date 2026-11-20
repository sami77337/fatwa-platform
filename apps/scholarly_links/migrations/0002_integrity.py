"""Immutable versions and links; PostgreSQL serializes graph decisions and pins."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION sl_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'scholarly identity immutable' USING ERRCODE='23514'; END IF;
 IF NEW.id=NEW.public_id THEN RAISE EXCEPTION 'separate public identity required' USING ERRCODE='23514'; END IF;
 NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;
CREATE FUNCTION sl_identity_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='scholarly_links_lessonseries' THEN
  IF NOT EXISTS(SELECT 1 FROM scholarly_links_seriesversion WHERE series_id=NEW.id) THEN
   RAISE EXCEPTION 'series initial version required' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM scholarly_links_lessonversion WHERE lesson_id=NEW.id) THEN
   RAISE EXCEPTION 'lesson initial version required' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER sl_series_identity BEFORE INSERT OR UPDATE OR DELETE ON scholarly_links_lessonseries FOR EACH ROW EXECUTE FUNCTION sl_identity_guard();
CREATE TRIGGER sl_lesson_identity BEFORE INSERT OR UPDATE OR DELETE ON scholarly_links_lesson FOR EACH ROW EXECUTE FUNCTION sl_identity_guard();
CREATE CONSTRAINT TRIGGER sl_series_complete AFTER INSERT ON scholarly_links_lessonseries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sl_identity_complete();
CREATE CONSTRAINT TRIGGER sl_lesson_complete AFTER INSERT ON scholarly_links_lesson DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sl_identity_complete();

CREATE FUNCTION sl_sealed_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id uuid; target_id uuid; c casework_case%ROWTYPE; t casework_case%ROWTYPE;
 body jsonb; prior_hash text; prior_count integer; prior_action text;
 sv scholarly_links_seriesversion%ROWTYPE; lv scholarly_links_lessonversion%ROWTYPE;
 rel scholarly_links_caserelation%ROWTYPE; ll scholarly_links_caselessonlink%ROWTYPE;
 a casework_answerrevision%ROWTYPE; b casework_answerrevision%ROWTYPE;
 p answer_media_answerpart%ROWTYPE; m answer_media_answermanifest%ROWTYPE;
 expected_source jsonb; last_parent_hash text; cycle_found boolean;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'scholarly history immutable' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','sha256','created_at','transaction_id'];
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM body
  OR NEW.sha256<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
 THEN RAISE EXCEPTION 'scholarly seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='scholarly_links_lessoncategory' THEN owner_id:=NEW.case_id;
 ELSIF TG_TABLE_NAME='scholarly_links_seriesversion' THEN
  SELECT case_id INTO owner_id FROM scholarly_links_lessonseries WHERE id=NEW.series_id;
 ELSIF TG_TABLE_NAME='scholarly_links_lessonversion' THEN
  SELECT s.case_id INTO owner_id FROM scholarly_links_lesson l JOIN scholarly_links_lessonseries s ON s.id=l.series_id WHERE l.id=NEW.lesson_id;
 ELSIF TG_TABLE_NAME='scholarly_links_caserelation' THEN
  PERFORM pg_advisory_xact_lock(546131,1);
  owner_id:=NEW.source_case_id; target_id:=NEW.target_case_id;
 ELSIF TG_TABLE_NAME='scholarly_links_caselessonlink' THEN
  owner_id:=NEW.case_id;
  SELECT s.case_id INTO target_id FROM scholarly_links_lessonversion v JOIN scholarly_links_lesson l ON l.id=v.lesson_id JOIN scholarly_links_lessonseries s ON s.id=l.series_id WHERE v.id=NEW.lesson_version_id;
 ELSIF TG_TABLE_NAME='scholarly_links_linkdecision' THEN
  IF NEW.relation_id IS NOT NULL THEN
   PERFORM pg_advisory_xact_lock(546131,1);
   SELECT * INTO rel FROM scholarly_links_caserelation WHERE id=NEW.relation_id;
   owner_id:=rel.source_case_id; target_id:=rel.target_case_id; last_parent_hash:=rel.sha256;
  ELSE
   SELECT * INTO ll FROM scholarly_links_caselessonlink WHERE id=NEW.lesson_link_id;
   owner_id:=ll.case_id; last_parent_hash:=ll.sha256;
   SELECT s.case_id INTO target_id FROM scholarly_links_lessonversion v JOIN scholarly_links_lesson l ON l.id=v.lesson_id JOIN scholarly_links_lessonseries s ON s.id=l.series_id WHERE v.id=ll.lesson_version_id;
  END IF;
 ELSE RAISE EXCEPTION 'unknown scholarly table' USING ERRCODE='23514'; END IF;
 PERFORM id FROM casework_case WHERE id IN (owner_id,target_id) ORDER BY id FOR UPDATE;
 SELECT * INTO c FROM casework_case WHERE id=owner_id;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version THEN
  RAISE EXCEPTION 'scholarly canonical pins changed' USING ERRCODE='23514'; END IF;
 IF target_id IS NOT NULL THEN
  SELECT * INTO t FROM casework_case WHERE id=target_id;
  IF NOT FOUND OR t.revision<>NEW.target_case_revision OR t.evidence_version<>NEW.target_evidence_version THEN
   RAISE EXCEPTION 'scholarly target pins changed' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='scholarly_links_lessoncategory' THEN
  IF btrim(NEW.label)='' OR (SELECT count(*) FROM scholarly_links_lessoncategory WHERE case_id=owner_id)>=64 THEN
   RAISE EXCEPTION 'lesson category invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='scholarly_links_seriesversion' THEN
  SELECT count(*) INTO prior_count FROM scholarly_links_seriesversion WHERE series_id=NEW.series_id;
  SELECT sha256 INTO prior_hash FROM scholarly_links_seriesversion WHERE series_id=NEW.series_id ORDER BY number DESC LIMIT 1;
  IF NEW.number<>prior_count+1 OR NEW.previous_sha256<>coalesce(prior_hash,repeat('0',64))
   OR btrim(NEW.title)='' OR jsonb_typeof(NEW.teachers)<>'array' OR jsonb_array_length(NEW.teachers) NOT BETWEEN 1 AND 8
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.teachers) e WHERE jsonb_typeof(e)<>'object'
     OR jsonb_typeof(e->'name') IS DISTINCT FROM 'string' OR length(btrim(e->>'name')) NOT BETWEEN 1 AND 160
     OR (e ? 'provider_id')<>(e ? 'subject_id')
     OR e-ARRAY['name','provider_id','subject_id']<>'{}'::jsonb
     OR ((e ? 'provider_id') AND (jsonb_typeof(e->'provider_id') IS DISTINCT FROM 'string' OR jsonb_typeof(e->'subject_id') IS DISTINCT FROM 'string'
      OR e->>'provider_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' OR e->>'subject_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')))
   OR jsonb_typeof(NEW.lesson_order)<>'array' OR jsonb_array_length(NEW.lesson_order)>64
   OR (SELECT count(DISTINCT x) FROM jsonb_array_elements_text(NEW.lesson_order) x)<>jsonb_array_length(NEW.lesson_order)
   OR (SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) FROM jsonb_array_elements_text(NEW.lesson_order) x)
     IS DISTINCT FROM (SELECT coalesce(jsonb_agg(id::text ORDER BY id::text),'[]'::jsonb) FROM scholarly_links_lesson WHERE series_id=NEW.series_id)
  THEN RAISE EXCEPTION 'lesson series history invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='scholarly_links_lessonversion' THEN
  SELECT count(*) INTO prior_count FROM scholarly_links_lessonversion WHERE lesson_id=NEW.lesson_id;
  SELECT sha256 INTO prior_hash FROM scholarly_links_lessonversion WHERE lesson_id=NEW.lesson_id ORDER BY number DESC LIMIT 1;
  SELECT * INTO sv FROM scholarly_links_seriesversion WHERE id=NEW.series_version_id;
  IF NEW.number<>prior_count+1 OR NEW.previous_sha256<>coalesce(prior_hash,repeat('0',64))
   OR btrim(NEW.title)='' OR btrim(NEW.provenance)=''
   OR NOT EXISTS(SELECT 1 FROM scholarly_links_lesson WHERE id=NEW.lesson_id AND series_id=sv.series_id)
   OR NOT (sv.lesson_order ? NEW.lesson_id::text)
   OR NOT EXISTS(SELECT 1 FROM scholarly_links_lessoncategory WHERE id=NEW.category_id AND case_id=owner_id)
  THEN RAISE EXCEPTION 'lesson version history invalid' USING ERRCODE='23514'; END IF;
  IF NEW.source_part_id IS NULL THEN
   IF NEW.source_snapshot<>'{}'::jsonb THEN RAISE EXCEPTION 'empty lesson source required' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO p FROM answer_media_answerpart WHERE id=NEW.source_part_id;
   SELECT * INTO m FROM answer_media_answermanifest WHERE answer_id=p.manifest_id;
   SELECT * INTO a FROM casework_answerrevision WHERE id=m.answer_id;
   expected_source:=jsonb_build_object('kind','ANSWER_MEDIA','part_id',p.id::text,'answer_id',a.id::text,
     'answer_revision',a.revision,'evidence_version',a.evidence_version,'manifest_sha256',m.sha256,
     'sha256',p.sha256,'size',p.size,'media_type',p.media_type,
     'duration_ms',CASE WHEN p.kind='AUDIO' THEN floor((p.metadata->>'duration_seconds')::numeric*1000)::integer ELSE NULL END,
     'authored_by',a.subject_id,'author_provider',a.provider_id);
   IF a.case_id IS DISTINCT FROM owner_id OR p.ordinal<=1 OR NEW.source_snapshot IS DISTINCT FROM expected_source THEN
    RAISE EXCEPTION 'lesson source pins invalid' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='scholarly_links_caserelation' THEN
  SELECT * INTO a FROM casework_answerrevision WHERE id=NEW.source_answer_id;
  SELECT * INTO b FROM casework_answerrevision WHERE id=NEW.target_answer_id;
  IF a.case_id IS DISTINCT FROM owner_id OR b.case_id IS DISTINCT FROM target_id
   OR a.revision<>c.answer_revision OR a.evidence_version<>c.evidence_version
   OR a.text_sha256<>NEW.source_answer_sha256 OR b.text_sha256<>NEW.target_answer_sha256
   OR btrim(NEW.reason)='' OR NOT EXISTS(SELECT 1 FROM casework_casedecision WHERE answer_id=b.id AND case_id=target_id AND action='APPROVE')
   OR EXISTS(SELECT 1 FROM scholarly_links_caserelation r WHERE r.source_answer_id=a.id AND r.target_answer_id=b.id AND r.kind=NEW.kind
    AND coalesce((SELECT action FROM scholarly_links_linkdecision WHERE relation_id=r.id ORDER BY sequence DESC LIMIT 1),'PROPOSED') NOT IN ('REJECT','WITHDRAW'))
   OR (SELECT count(*) FROM scholarly_links_caserelation WHERE source_case_id=owner_id)>=128
  THEN RAISE EXCEPTION 'case relation invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='scholarly_links_caselessonlink' THEN
  SELECT * INTO a FROM casework_answerrevision WHERE id=NEW.answer_id;
  SELECT * INTO lv FROM scholarly_links_lessonversion WHERE id=NEW.lesson_version_id;
  IF a.case_id IS DISTINCT FROM owner_id OR a.revision<>c.answer_revision OR a.evidence_version<>c.evidence_version
   OR a.text_sha256<>NEW.answer_sha256 OR btrim(NEW.reason)=''
   OR (NEW.start_ms IS NOT NULL AND (lv.source_snapshot->>'duration_ms' IS NULL
    OR NEW.start_ms >= (lv.source_snapshot->>'duration_ms')::integer
    OR NEW.end_ms > (lv.source_snapshot->>'duration_ms')::integer))
   OR EXISTS(SELECT 1 FROM scholarly_links_caselessonlink l WHERE l.answer_id=a.id AND l.lesson_version_id=lv.id
    AND l.start_ms IS NOT DISTINCT FROM NEW.start_ms AND l.end_ms IS NOT DISTINCT FROM NEW.end_ms
    AND coalesce((SELECT action FROM scholarly_links_linkdecision WHERE lesson_link_id=l.id ORDER BY sequence DESC LIMIT 1),'PROPOSED') NOT IN ('REJECT','WITHDRAW'))
   OR (SELECT count(*) FROM scholarly_links_caselessonlink WHERE case_id=owner_id)>=128
  THEN RAISE EXCEPTION 'case lesson link invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='scholarly_links_linkdecision' THEN
  SELECT count(*) INTO prior_count FROM scholarly_links_linkdecision
   WHERE (NEW.relation_id IS NOT NULL AND relation_id=NEW.relation_id) OR (NEW.lesson_link_id IS NOT NULL AND lesson_link_id=NEW.lesson_link_id);
  SELECT sha256,action INTO prior_hash,prior_action FROM scholarly_links_linkdecision
   WHERE (NEW.relation_id IS NOT NULL AND relation_id=NEW.relation_id) OR (NEW.lesson_link_id IS NOT NULL AND lesson_link_id=NEW.lesson_link_id)
   ORDER BY sequence DESC LIMIT 1;
  IF NEW.sequence<>prior_count+1 OR NEW.previous_sha256<>coalesce(prior_hash,last_parent_hash)
   OR btrim(NEW.note)='' OR NOT ((prior_count=0 AND NEW.action IN ('APPROVE','REJECT')) OR (prior_count=1 AND prior_action='APPROVE' AND NEW.action='WITHDRAW'))
  THEN RAISE EXCEPTION 'scholarly decision invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action='APPROVE' AND NEW.relation_id IS NOT NULL AND rel.kind IN ('DUPLICATE_OF','SUPERSEDES') THEN
   WITH RECURSIVE edges AS (
    SELECT r.source_case_id AS s,r.target_case_id AS t FROM scholarly_links_caserelation r WHERE r.kind=rel.kind
      AND (SELECT action FROM scholarly_links_linkdecision WHERE relation_id=r.id ORDER BY sequence DESC LIMIT 1)='APPROVE'
   ), reachable(id) AS (
    SELECT rel.target_case_id UNION SELECT edges.t FROM edges JOIN reachable ON edges.s=reachable.id
   ) SELECT EXISTS(SELECT 1 FROM reachable WHERE id=rel.source_case_id) INTO cycle_found;
   IF cycle_found THEN RAISE EXCEPTION 'cyclic scholarly relation' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.transaction_id:=txid_current(); NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;
"""

TABLES = (
    "lessoncategory",
    "seriesversion",
    "lessonversion",
    "caserelation",
    "caselessonlink",
    "linkdecision",
)
for table in TABLES:
    SQL += f"\nCREATE TRIGGER sl_{table}_guard BEFORE INSERT OR UPDATE OR DELETE ON scholarly_links_{table} FOR EACH ROW EXECUTE FUNCTION sl_sealed_guard();\n"

REVERSE = (
    "\n".join(f"DROP TRIGGER sl_{table}_guard ON scholarly_links_{table};" for table in TABLES)
    + """
DROP TRIGGER sl_series_complete ON scholarly_links_lessonseries;
DROP TRIGGER sl_lesson_complete ON scholarly_links_lesson;
DROP TRIGGER sl_series_identity ON scholarly_links_lessonseries;
DROP TRIGGER sl_lesson_identity ON scholarly_links_lesson;
DROP FUNCTION sl_sealed_guard();
DROP FUNCTION sl_identity_complete();
DROP FUNCTION sl_identity_guard();
"""
)


class Migration(migrations.Migration):
    dependencies = [("scholarly_links", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
