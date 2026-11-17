from django.db import migrations

SQL = """
CREATE FUNCTION answer_media_manifest_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'answer manifest immutable' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM casework_answerrevision a JOIN casework_case c ON c.id=a.case_id
  JOIN casework_caseevent e ON e.case_id=c.id AND e.sequence=c.revision
  WHERE a.id=NEW.answer_id AND a.created_at>=transaction_timestamp()
    AND a.revision=c.answer_revision AND a.evidence_version=c.evidence_version
    AND c.stage='UNDER_REVIEW' AND c.approved_answer_id IS NULL
    AND e.action='SAVE_ANSWER' AND e.answer_id=a.id
 ) THEN RAISE EXCEPTION 'answer manifest binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER answer_media_manifest_guard BEFORE INSERT OR UPDATE OR DELETE
 ON answer_media_answermanifest FOR EACH ROW EXECUTE FUNCTION answer_media_manifest_guard();

CREATE FUNCTION answer_media_part_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a casework_answerrevision%ROWTYPE; m answer_media_answermanifest%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'answer parts immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO m FROM answer_media_answermanifest WHERE answer_id=NEW.manifest_id;
 SELECT * INTO a FROM casework_answerrevision WHERE id=m.answer_id;
 PERFORM 1 FROM casework_case WHERE id=a.case_id FOR UPDATE;
 IF a.created_at < transaction_timestamp() OR NEW.ordinal>m.part_count
   OR NOT EXISTS (SELECT 1 FROM casework_case WHERE id=a.case_id
       AND stage='UNDER_REVIEW' AND approved_answer_id IS NULL
       AND answer_revision=a.revision AND evidence_version=a.evidence_version)
   OR EXISTS (SELECT 1 FROM casework_casedecision WHERE answer_id=a.id)
   OR NEW.size<>octet_length(NEW.original)
   OR NEW.sha256<>encode(sha256(NEW.original),'hex')
   OR (NEW.ordinal=1 AND (NEW.kind<>'TEXT' OR NEW.original<>convert_to(a.text,'UTF8')
                         OR NEW.filename<>'' OR NEW.media_type<>'text/plain'))
   OR (NEW.ordinal>1 AND (NEW.kind='TEXT' OR NEW.filename=''))
 THEN RAISE EXCEPTION 'answer part binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER answer_media_part_guard BEFORE INSERT OR UPDATE OR DELETE
 ON answer_media_answerpart FOR EACH ROW EXECUTE FUNCTION answer_media_part_guard();

CREATE FUNCTION answer_media_manifest_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM answer_media_answerpart WHERE manifest_id=NEW.answer_id)<>NEW.part_count
 THEN RAISE EXCEPTION 'answer manifest incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER answer_media_manifest_complete AFTER INSERT ON answer_media_answermanifest
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION answer_media_manifest_complete();

CREATE FUNCTION answer_media_release_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'private answer release immutable' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM answer_media_answermanifest m
  JOIN casework_answerrevision a ON a.id=m.answer_id
  JOIN casework_case c ON c.id=a.case_id
  JOIN casework_casedecision d ON d.id=NEW.decision_id
  WHERE m.answer_id=NEW.manifest_id AND m.sha256=NEW.manifest_sha256
    AND c.stage='ANSWERED' AND c.approved_answer_id=a.id AND c.answer_revision=a.revision
    AND c.evidence_version=NEW.evidence_version AND a.evidence_version=NEW.evidence_version
    AND d.answer_id=a.id AND d.case_id=c.id AND d.action='APPROVE'
    AND d.evidence_version=NEW.evidence_version
    AND d.subject_id=NEW.subject_id AND d.provider_id=NEW.provider_id
    AND d.auth_epoch=NEW.auth_epoch
 ) THEN RAISE EXCEPTION 'private release binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER answer_media_release_guard BEFORE INSERT OR UPDATE OR DELETE
 ON answer_media_privateanswerrelease FOR EACH ROW EXECUTE FUNCTION answer_media_release_guard();
"""

REVERSE = """
DROP TRIGGER answer_media_release_guard ON answer_media_privateanswerrelease;
DROP FUNCTION answer_media_release_guard();
DROP TRIGGER answer_media_manifest_complete ON answer_media_answermanifest;
DROP FUNCTION answer_media_manifest_complete();
DROP TRIGGER answer_media_part_guard ON answer_media_answerpart;
DROP FUNCTION answer_media_part_guard();
DROP TRIGGER answer_media_manifest_guard ON answer_media_answermanifest;
DROP FUNCTION answer_media_manifest_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("answer_media", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
