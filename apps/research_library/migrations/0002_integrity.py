"""Immutable source editions, independently attributed decisions, and exact chains."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION rl_blob_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'library blob immutable' USING ERRCODE='23514'; END IF;
 IF NEW.validation->'validated' IS DISTINCT FROM 'true'::jsonb
  OR (NEW.storage_backend='inline-database-v1' AND
      (NEW.original IS NULL OR octet_length(NEW.original)<>NEW.size OR encode(sha256(NEW.original),'hex')<>NEW.sha256))
  OR (NEW.storage_backend<>'inline-database-v1' AND
      (NEW.storage_backend<>'private-filesystem-v1' OR NEW.original IS NOT NULL OR NEW.storage_key<>NEW.sha256||'.blob'))
 THEN RAISE EXCEPTION 'library blob invalid' USING ERRCODE='23514'; END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER rl_blob_guard BEFORE INSERT OR UPDATE OR DELETE ON research_library_libraryblob
 FOR EACH ROW EXECUTE FUNCTION rl_blob_guard();

CREATE FUNCTION rl_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'library item immutable' USING ERRCODE='23514'; END IF;
 IF NEW.id=NEW.public_id OR NEW.namespace !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$'
  OR NEW.external_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$'
 THEN RAISE EXCEPTION 'library identity invalid' USING ERRCODE='23514'; END IF;
 PERFORM id FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF (SELECT count(*) FROM research_library_libraryitem WHERE case_id=NEW.case_id)>=64 THEN
  RAISE EXCEPTION 'library item capacity' USING ERRCODE='23514'; END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER rl_item_guard BEFORE INSERT OR UPDATE OR DELETE ON research_library_libraryitem
 FOR EACH ROW EXECUTE FUNCTION rl_item_guard();
CREATE FUNCTION rl_item_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM research_library_libraryversion WHERE item_id=NEW.id) THEN
  RAISE EXCEPTION 'library first edition required' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER rl_item_complete AFTER INSERT ON research_library_libraryitem
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION rl_item_complete();

CREATE FUNCTION rl_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; owner_id uuid; c casework_case%ROWTYPE;
 old research_library_libraryversion%ROWTYPE; v research_library_libraryversion%ROWTYPE;
 prior research_library_librarydecision%ROWTYPE; review research_library_librarydecision%ROWTYPE;
 approval research_library_librarydecision%ROWTYPE; n integer; blob research_library_libraryblob%ROWTYPE;
 field_name text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'library history immutable' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 IF TG_TABLE_NAME='research_library_librarydecision' THEN
  IF NEW.valid_until IS NOT NULL THEN
   body:=jsonb_set(body,'{valid_until}',to_jsonb(to_char(NEW.valid_until AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
  END IF;
 END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM body
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
 THEN RAISE EXCEPTION 'library seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='research_library_libraryversion' THEN
  SELECT case_id INTO owner_id FROM research_library_libraryitem WHERE id=NEW.item_id;
 ELSE
  SELECT * INTO v FROM research_library_libraryversion WHERE id=NEW.version_id;
  SELECT case_id INTO owner_id FROM research_library_libraryitem WHERE id=v.item_id;
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=owner_id FOR UPDATE;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version THEN
  RAISE EXCEPTION 'library case pins invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='research_library_libraryversion' THEN
  SELECT * INTO old FROM research_library_libraryversion WHERE item_id=NEW.item_id ORDER BY number DESC LIMIT 1;
  SELECT count(*) INTO n FROM research_library_libraryversion WHERE item_id=NEW.item_id;
  IF NEW.number<>n+1 OR NEW.previous_id IS DISTINCT FROM old.id OR jsonb_typeof(NEW.payload)<>'object'
   OR (NEW.payload-ARRAY['kind','language','synthetic','title','work_title','edition_label','creator','description','source_locator','provenance','rights_basis','source_version','recorded_text'])<>'{}'::jsonb
   OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>13
   OR jsonb_typeof(NEW.payload->'kind') IS DISTINCT FROM 'string'
   OR jsonb_typeof(NEW.payload->'language') IS DISTINCT FROM 'string'
   OR NEW.payload->>'kind' NOT IN ('BOOK','DOCUMENT','IMAGE','AUDIO','VIDEO')
   OR NEW.payload->>'language' NOT IN ('ar','en') OR NEW.payload->'synthetic' IS DISTINCT FROM 'true'::jsonb
   OR (old.id IS NOT NULL AND old.payload->>'kind'<>NEW.payload->>'kind')
  THEN RAISE EXCEPTION 'library edition identity invalid' USING ERRCODE='23514'; END IF;
  FOREACH field_name IN ARRAY ARRAY['title','work_title','edition_label','creator','description','source_locator','provenance','rights_basis','source_version','recorded_text'] LOOP
   IF jsonb_typeof(NEW.payload->field_name) IS DISTINCT FROM 'string'
    OR length(NEW.payload->>field_name)>(CASE WHEN field_name='recorded_text' THEN 10000 WHEN field_name='description' THEN 2000 WHEN field_name IN ('provenance','rights_basis','source_locator') THEN 1000 WHEN field_name='source_version' THEN 128 WHEN field_name='edition_label' THEN 160 ELSE 200 END)
    OR (field_name IN ('title','work_title','provenance','rights_basis','source_version') AND btrim(NEW.payload->>field_name)='')
   THEN RAISE EXCEPTION 'library edition field invalid' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF NEW.blob_id IS NULL THEN
   IF NEW.filename<>'' THEN RAISE EXCEPTION 'library file absent' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO blob FROM research_library_libraryblob WHERE sha256=NEW.blob_id;
   IF NOT FOUND OR NEW.filename !~ '^[A-Za-z0-9][A-Za-z0-9_. -]{0,94}\.[A-Za-z0-9]{2,4}$'
    OR (NEW.payload->>'kind' IN ('BOOK','DOCUMENT') AND blob.media_type NOT IN ('application/pdf','text/plain'))
    OR (NEW.payload->>'kind'='IMAGE' AND blob.media_type NOT LIKE 'image/%')
    OR (NEW.payload->>'kind'='AUDIO' AND blob.media_type NOT LIKE 'audio/%')
    OR (NEW.payload->>'kind'='VIDEO' AND blob.media_type NOT IN ('video/mp4','video/webm'))
   THEN RAISE EXCEPTION 'library file binding invalid' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  SELECT count(*) INTO n FROM research_library_librarydecision WHERE version_id=NEW.version_id;
  SELECT * INTO prior FROM research_library_librarydecision WHERE version_id=NEW.version_id ORDER BY sequence DESC LIMIT 1;
  SELECT * INTO review FROM research_library_librarydecision WHERE version_id=NEW.version_id AND action='REVIEW';
  SELECT * INTO approval FROM research_library_librarydecision WHERE version_id=NEW.version_id AND action='APPROVE';
  IF NEW.sequence<>n+1 OR NEW.previous_digest<>coalesce(prior.digest,v.digest) OR btrim(NEW.note)=''
   OR EXISTS(SELECT 1 FROM research_library_librarydecision WHERE version_id=NEW.version_id AND action='WITHDRAW')
   OR jsonb_typeof(NEW.uses)<>'array' OR jsonb_array_length(NEW.uses)>7
   OR (SELECT count(DISTINCT x) FROM jsonb_array_elements_text(NEW.uses) x)<>jsonb_array_length(NEW.uses)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.uses) x WHERE x NOT IN ('READ','DOWNLOAD','CITE','EXPORT','OFFLINE','PUBLIC_METADATA','PUBLIC_CONTENT'))
   OR (NEW.action<>'APPROVE' AND NEW.uses<>'[]'::jsonb)
  THEN RAISE EXCEPTION 'library decision sequence invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action IN ('APPROVE','RELEASE') THEN
   IF NEW.valid_until IS NULL OR NEW.valid_until<=clock_timestamp() OR NEW.valid_until>clock_timestamp()+interval '1 hour' THEN
    RAISE EXCEPTION 'library lease invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.valid_until IS NOT NULL THEN RAISE EXCEPTION 'library unexpected lease' USING ERRCODE='23514'; END IF;
  IF NEW.action='REVIEW' THEN
   IF n<>0 OR (NEW.provider_id=v.provider_id AND NEW.subject_id=v.subject_id) THEN
    RAISE EXCEPTION 'library independent review required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='APPROVE' THEN
   IF n<>1 OR review.id IS NULL OR jsonb_array_length(NEW.uses)=0
    OR (NEW.provider_id=v.provider_id AND NEW.subject_id=v.subject_id)
    OR (NEW.provider_id=review.provider_id AND NEW.subject_id=review.subject_id)
    OR (NEW.uses ? 'PUBLIC_CONTENT' AND NOT NEW.uses ? 'PUBLIC_METADATA')
    OR (v.blob_id IS NULL AND (NEW.uses ? 'READ' OR NEW.uses ? 'DOWNLOAD'))
   THEN RAISE EXCEPTION 'library independent approval required' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='RELEASE' THEN
   IF n<>2 OR approval.id IS NULL OR NOT approval.uses ? 'PUBLIC_METADATA' OR NEW.valid_until>approval.valid_until THEN
    RAISE EXCEPTION 'library release invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.action='REVOKE' THEN
   IF NOT EXISTS(SELECT 1 FROM research_library_librarydecision WHERE version_id=NEW.version_id AND action='RELEASE') THEN
    RAISE EXCEPTION 'library release missing' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER rl_version_guard BEFORE INSERT OR UPDATE OR DELETE ON research_library_libraryversion FOR EACH ROW EXECUTE FUNCTION rl_history_guard();
CREATE TRIGGER rl_decision_guard BEFORE INSERT OR UPDATE OR DELETE ON research_library_librarydecision FOR EACH ROW EXECUTE FUNCTION rl_history_guard();
"""

REVERSE = """
DROP TRIGGER rl_decision_guard ON research_library_librarydecision;
DROP TRIGGER rl_version_guard ON research_library_libraryversion;
DROP FUNCTION rl_history_guard();
DROP TRIGGER rl_item_complete ON research_library_libraryitem;
DROP FUNCTION rl_item_complete();
DROP TRIGGER rl_item_guard ON research_library_libraryitem;
DROP FUNCTION rl_item_guard();
DROP TRIGGER rl_blob_guard ON research_library_libraryblob;
DROP FUNCTION rl_blob_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("research_library", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
