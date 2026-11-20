from django.db import migrations

SQL = r"""
CREATE FUNCTION cs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'search generations are immutable derived history' USING ERRCODE='23514';
END $$;

CREATE FUNCTION cs_generation_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c record; previous integer;
BEGIN
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 SELECT coalesce(max(number),0) INTO previous FROM canonical_search_searchgeneration WHERE case_id=NEW.case_id;
 IF c.id IS NULL OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version
 OR NEW.number<>previous+1 OR NEW.profile<>'ar-simple-trigram-dev-v1'
 OR NEW.source_fingerprint!~'^[a-f0-9]{64}$'
 OR jsonb_typeof(NEW.manifest) IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.manifest) NOT BETWEEN 1 AND 512
 OR octet_length(NEW.manifest::text)>524288
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR NEW.canonical_payload::jsonb IS DISTINCT FROM
     to_jsonb(NEW)-ARRAY['canonical_payload','digest','transaction_id','created_at']
 OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')<>NEW.digest
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.manifest) m WHERE
    jsonb_typeof(m) IS DISTINCT FROM 'object'
    OR NOT (m ?& ARRAY['kind','source_id','pin','derived_sha256'])
    OR jsonb_typeof(m->'pin') IS DISTINCT FROM 'object'
    OR NOT ((m->'pin') ?& ARRAY['kind','case_id','source_id','source_sha256','text_sha256','version'])
    OR m->>'kind' IS DISTINCT FROM m->'pin'->>'kind'
    OR m->>'source_id' IS DISTINCT FROM m->'pin'->>'source_id'
    OR m->'pin'->>'case_id' IS DISTINCT FROM NEW.case_id::text
    OR (m->>'derived_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
    OR (m->'pin'->>'text_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
    OR (m->'pin'->>'source_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE)
 THEN RAISE EXCEPTION 'invalid search generation source pins' USING ERRCODE='23514'; END IF;
 NEW.transaction_id:=txid_current();
 NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE FUNCTION cs_document_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE g record; c record; item jsonb; source_text text; source_hash text;
BEGIN
 SELECT * INTO g FROM canonical_search_searchgeneration WHERE id=NEW.generation_id;
 IF g.id IS NULL THEN RAISE EXCEPTION 'missing search generation' USING ERRCODE='23514'; END IF;
 SELECT * INTO c FROM casework_case WHERE id=g.case_id FOR UPDATE;
 item:=g.manifest->(NEW.ordinal-1);
 IF g.transaction_id<>txid_current() OR c.revision<>g.case_revision OR c.evidence_version<>g.evidence_version
 OR NEW.ordinal<>(SELECT count(*)+1 FROM canonical_search_searchdocument WHERE generation_id=g.id)
 OR item IS NULL OR item->>'kind' IS DISTINCT FROM NEW.kind
 OR item->>'source_id' IS DISTINCT FROM NEW.source_id::text
 OR item->'pin' IS DISTINCT FROM NEW.pin
 OR length(NEW.original_text) NOT BETWEEN 1 AND 16000 OR btrim(NEW.original_text)=''
 OR length(NEW.normalized_text)>48000
 OR encode(sha256(convert_to(NEW.original_text,'UTF8')),'hex') IS DISTINCT FROM NEW.pin->>'text_sha256'
 OR encode(sha256(convert_to(NEW.normalized_text,'UTF8')),'hex') IS DISTINCT FROM item->>'derived_sha256'
 OR NEW.canonical_payload::jsonb IS DISTINCT FROM
     to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at','vector']
 OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')<>NEW.digest
 THEN RAISE EXCEPTION 'invalid search document generation binding' USING ERRCODE='23514'; END IF;
 IF NEW.kind='QUESTION' THEN
   SELECT original_question,question_sha256 INTO source_text,source_hash FROM casework_casesource
   WHERE case_id=g.case_id AND case_id=NEW.source_id;
 ELSIF NEW.kind='FOLLOWUP' THEN
   SELECT e.text,e.text_sha256 INTO source_text,source_hash FROM casework_caseevidence e
   WHERE e.case_id=g.case_id AND e.id=NEW.source_id AND e.kind='FOLLOWUP'
   AND NOT EXISTS(SELECT 1 FROM transcript_case_links_transcriptlink t WHERE t.evidence_id=e.id);
 ELSIF NEW.kind='ANSWER' THEN
   SELECT a.text,a.text_sha256 INTO source_text,source_hash FROM casework_answerrevision a
   WHERE a.case_id=g.case_id AND a.id=NEW.source_id AND a.revision=c.answer_revision
   AND a.evidence_version=c.evidence_version;
 ELSIF NEW.kind='TRANSCRIPT' THEN
   IF NOT EXISTS(SELECT 1 FROM transcript_case_links_transcriptlink t
      JOIN transcript_case_links_transcriptupload u ON u.id=t.upload_id
      WHERE t.case_id=g.case_id AND t.id=NEW.source_id AND
      u.id::text=NEW.pin->>'upload_id' AND u.sha256=NEW.pin->>'upload_sha256')
   THEN RAISE EXCEPTION 'search transcript source mismatch' USING ERRCODE='23514'; END IF;
   source_text:=NEW.original_text; source_hash:=NEW.pin->>'source_sha256';
 ELSE
   RAISE EXCEPTION 'search source adapter unavailable' USING ERRCODE='23514';
 END IF;
 IF source_text IS DISTINCT FROM NEW.original_text OR source_hash IS DISTINCT FROM NEW.pin->>'source_sha256'
 THEN RAISE EXCEPTION 'search document differs from canonical source' USING ERRCODE='23514'; END IF;
 NEW.vector:=to_tsvector('pg_catalog.simple'::regconfig,NEW.normalized_text);
 NEW.created_at:=clock_timestamp();
 RETURN NEW;
END $$;

CREATE FUNCTION cs_generation_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM canonical_search_searchdocument WHERE generation_id=NEW.id)
     <>jsonb_array_length(NEW.manifest)
 THEN RAISE EXCEPTION 'incomplete search generation' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;

CREATE TRIGGER cs_generation_insert BEFORE INSERT ON canonical_search_searchgeneration
 FOR EACH ROW EXECUTE FUNCTION cs_generation_insert();
CREATE TRIGGER cs_generation_immutable BEFORE UPDATE OR DELETE ON canonical_search_searchgeneration
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
CREATE TRIGGER cs_document_insert BEFORE INSERT ON canonical_search_searchdocument
 FOR EACH ROW EXECUTE FUNCTION cs_document_insert();
CREATE TRIGGER cs_document_immutable BEFORE UPDATE OR DELETE ON canonical_search_searchdocument
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
CREATE CONSTRAINT TRIGGER cs_generation_complete AFTER INSERT ON canonical_search_searchgeneration
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cs_generation_complete();
"""

REVERSE = """
DROP TRIGGER cs_generation_complete ON canonical_search_searchgeneration;
DROP TRIGGER cs_generation_insert ON canonical_search_searchgeneration;
DROP TRIGGER cs_generation_immutable ON canonical_search_searchgeneration;
DROP TRIGGER cs_document_insert ON canonical_search_searchdocument;
DROP TRIGGER cs_document_immutable ON canonical_search_searchdocument;
DROP FUNCTION cs_generation_complete();
DROP FUNCTION cs_document_insert();
DROP FUNCTION cs_generation_insert();
DROP FUNCTION cs_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("canonical_search", "0001_initial"),
        ("transcript_case_links", "0002_binding_guards"),
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
