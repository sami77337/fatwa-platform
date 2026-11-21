"""Database-enforced immutable sources, revision chains and independent decisions."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION pam_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; owner_id uuid; c casework_case%ROWTYPE;
 a answer_media_answerpart%ROWTYPE; m answer_media_answermanifest%ROWTYPE;
 answer casework_answerrevision%ROWTYPE; decision casework_casedecision%ROWTYPE;
 t public_answer_media_recordingtranscript%ROWTYPE;
 prior_t public_answer_media_recordingtranscript%ROWTYPE;
 e public_answer_media_publicmediaedition%ROWTYPE;
 prior_e public_answer_media_publicmediaedition%ROWTYPE;
 pub experimental_publication_publicationedition%ROWTYPE;
 prior_digest text; n integer; reviewer_provider text; reviewer_subject text;
 s jsonb; last_char integer:=0; last_time integer:=0; required_action text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'recording history immutable' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 IF TG_TABLE_NAME='public_answer_media_publicmediaaction' THEN
  IF NEW.valid_until IS NOT NULL THEN
   body:=jsonb_set(body,'{valid_until}',to_jsonb(to_char(NEW.valid_until AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
  END IF;
 END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM body
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR NEW.request_sha256 !~ '^[a-f0-9]{64}$'
  OR btrim(NEW.note)='' OR length(NEW.note)>1000
 THEN RAISE EXCEPTION 'recording seal invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME IN ('public_answer_media_recordingtranscript','public_answer_media_publicmediaedition') THEN
  owner_id:=NEW.case_id;
  SELECT * INTO a FROM answer_media_answerpart WHERE id=NEW.part_id;
 ELSIF TG_TABLE_NAME='public_answer_media_transcriptaction' THEN
  SELECT * INTO t FROM public_answer_media_recordingtranscript WHERE id=NEW.transcript_id;
  owner_id:=t.case_id;
  SELECT * INTO a FROM answer_media_answerpart WHERE id=t.part_id;
 ELSE
  SELECT * INTO e FROM public_answer_media_publicmediaedition WHERE id=NEW.edition_id;
  owner_id:=e.case_id;
  SELECT * INTO a FROM answer_media_answerpart WHERE id=e.part_id;
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=owner_id FOR UPDATE;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version THEN
  RAISE EXCEPTION 'recording case pins invalid' USING ERRCODE='23514'; END IF;
 SELECT * INTO m FROM answer_media_answermanifest WHERE answer_id=a.manifest_id;
 SELECT * INTO answer FROM casework_answerrevision WHERE id=m.answer_id;
 SELECT * INTO decision FROM casework_casedecision WHERE answer_id=answer.id;
 IF a.id IS NULL OR a.kind<>'AUDIO' OR answer.case_id<>c.id OR c.stage<>'ANSWERED'
  OR c.approved_answer_id IS DISTINCT FROM answer.id OR answer.evidence_version<>c.evidence_version
  OR c.answer_revision<>answer.revision OR decision.action IS DISTINCT FROM 'APPROVE'
  OR decision.evidence_version<>c.evidence_version
 THEN RAISE EXCEPTION 'recording original binding invalid' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME IN ('public_answer_media_recordingtranscript','public_answer_media_publicmediaedition') THEN
  IF jsonb_typeof(NEW.source_pins) IS DISTINCT FROM 'object'
   OR NEW.source_pins IS DISTINCT FROM jsonb_build_object(
      'answer_id',answer.id,'answer_revision',answer.revision,'answer_sha256',answer.text_sha256,
      'decision_id',decision.id,'evidence_version',answer.evidence_version,
      'manifest_sha256',m.sha256,'part_id',a.id,'part_sha256',a.sha256,'size',a.size,
      'media_type',a.media_type,'metadata_sha256',NEW.source_pins->>'metadata_sha256',
      'duration_ms',floor((a.metadata->>'duration_seconds')::numeric*1000)::integer)
   OR jsonb_typeof(NEW.source_pins->'metadata_sha256') IS DISTINCT FROM 'string'
   OR (NEW.source_pins->>'metadata_sha256') !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'recording exact source pins invalid' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='public_answer_media_recordingtranscript' THEN
  SELECT * INTO prior_t FROM public_answer_media_recordingtranscript WHERE part_id=NEW.part_id ORDER BY number DESC LIMIT 1;
  SELECT count(*) INTO n FROM public_answer_media_recordingtranscript WHERE part_id=NEW.part_id;
  IF NEW.number<>n+1 OR NEW.previous_id IS DISTINCT FROM prior_t.id
   OR btrim(NEW.text)='' OR length(NEW.text)>10000
   OR NEW.text_sha256<>encode(sha256(convert_to(NEW.text,'UTF8')),'hex')
   OR jsonb_typeof(NEW.segments) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.segments)>6
  THEN RAISE EXCEPTION 'recording revision invalid' USING ERRCODE='23514'; END IF;
  FOR s IN SELECT value FROM jsonb_array_elements(NEW.segments) LOOP
   IF jsonb_typeof(s) IS DISTINCT FROM 'object'
    OR (s-ARRAY['char_start','char_end','start_ms','end_ms','sha256'])<>'{}'::jsonb
    OR (SELECT count(*) FROM jsonb_object_keys(s))<>5
    OR jsonb_typeof(s->'char_start') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'char_end') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'start_ms') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'end_ms') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'sha256') IS DISTINCT FROM 'string'
    OR (s->>'char_start') !~ '^[0-9]+$' OR (s->>'char_end') !~ '^[0-9]+$'
    OR (s->>'start_ms') !~ '^[0-9]+$' OR (s->>'end_ms') !~ '^[0-9]+$'
    OR (s->>'char_start')::integer<last_char
    OR (s->>'char_end')::integer<=(s->>'char_start')::integer
    OR (s->>'char_end')::integer>length(NEW.text)
    OR (s->>'start_ms')::integer<last_time
    OR (s->>'end_ms')::integer<=(s->>'start_ms')::integer
    OR (s->>'end_ms')::integer>(NEW.source_pins->>'duration_ms')::integer
    OR s->>'sha256'<>encode(sha256(convert_to(substring(NEW.text FROM (s->>'char_start')::integer+1 FOR (s->>'char_end')::integer-(s->>'char_start')::integer),'UTF8')),'hex')
   THEN RAISE EXCEPTION 'recording documented segment invalid' USING ERRCODE='23514'; END IF;
   last_char:=(s->>'char_end')::integer; last_time:=(s->>'end_ms')::integer;
  END LOOP;
 ELSIF TG_TABLE_NAME='public_answer_media_transcriptaction' THEN
  SELECT count(*) INTO n FROM public_answer_media_transcriptaction WHERE transcript_id=t.id;
  SELECT digest INTO prior_digest FROM public_answer_media_transcriptaction WHERE transcript_id=t.id ORDER BY sequence DESC LIMIT 1;
  required_action:=CASE WHEN t.change_kind='MEANING_REVIEW' THEN 'APPROVE_MEANING' ELSE 'REVIEW' END;
  IF NEW.sequence<>n+1 OR NEW.previous_digest<>coalesce(prior_digest,t.digest)
   OR EXISTS(SELECT 1 FROM public_answer_media_transcriptaction WHERE transcript_id=t.id AND action='WITHDRAW')
   OR (NEW.action<>'WITHDRAW' AND (NEW.action<>required_action OR n<>0 OR (NEW.provider_id=t.provider_id AND NEW.subject_id=t.subject_id)))
  THEN RAISE EXCEPTION 'recording independent review invalid' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='public_answer_media_publicmediaedition' THEN
  SELECT * INTO prior_e FROM public_answer_media_publicmediaedition WHERE publication_id=NEW.publication_id AND part_id=NEW.part_id ORDER BY number DESC LIMIT 1;
  SELECT count(*) INTO n FROM public_answer_media_publicmediaedition WHERE publication_id=NEW.publication_id AND part_id=NEW.part_id;
  SELECT * INTO pub FROM experimental_publication_publicationedition WHERE id=NEW.publication_id;
  IF NEW.number<>n+1 OR NEW.previous_id IS DISTINCT FROM prior_e.id
   OR btrim(NEW.label)='' OR length(NEW.label)>120
   OR pub.case_id IS DISTINCT FROM c.id OR pub.answer_id IS DISTINCT FROM answer.id
   OR pub.content_sha256 IS DISTINCT FROM NEW.publication_sha256
   OR NOT EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=pub.id AND action='APPROVE')
   OR EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=pub.id AND action='WITHDRAW')
   OR EXISTS(SELECT 1 FROM experimental_publication_publicationedition p JOIN experimental_publication_publicationaction pa ON p.id=pa.edition_id WHERE p.case_id=c.id AND p.number>pub.number AND pa.action='APPROVE')
  THEN RAISE EXCEPTION 'recording publication binding invalid' USING ERRCODE='23514'; END IF;
  IF NEW.transcript_id IS NULL THEN
   IF NEW.transcript_digest<>'' THEN RAISE EXCEPTION 'recording missing transcript' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO t FROM public_answer_media_recordingtranscript WHERE id=NEW.transcript_id;
   IF t.case_id IS DISTINCT FROM c.id OR t.part_id IS DISTINCT FROM a.id OR t.digest IS DISTINCT FROM NEW.transcript_digest
    OR NOT EXISTS(SELECT 1 FROM public_answer_media_transcriptaction WHERE transcript_id=t.id AND action=CASE WHEN t.change_kind='MEANING_REVIEW' THEN 'APPROVE_MEANING' ELSE 'REVIEW' END)
    OR EXISTS(SELECT 1 FROM public_answer_media_transcriptaction WHERE transcript_id=t.id AND action='WITHDRAW')
   THEN RAISE EXCEPTION 'recording reviewed transcript required' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  SELECT * INTO pub FROM experimental_publication_publicationedition WHERE id=e.publication_id;
  IF pub.case_id IS DISTINCT FROM c.id OR pub.answer_id IS DISTINCT FROM answer.id
   OR pub.content_sha256 IS DISTINCT FROM e.publication_sha256
   OR NOT EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=pub.id AND action='APPROVE')
   OR EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=pub.id AND action='WITHDRAW')
   OR EXISTS(SELECT 1 FROM experimental_publication_publicationedition p JOIN experimental_publication_publicationaction pa ON p.id=pa.edition_id WHERE p.case_id=c.id AND p.number>pub.number AND pa.action='APPROVE')
  THEN RAISE EXCEPTION 'recording publication no longer current' USING ERRCODE='23514'; END IF;
  SELECT count(*) INTO n FROM public_answer_media_publicmediaaction WHERE edition_id=e.id;
  SELECT digest INTO prior_digest FROM public_answer_media_publicmediaaction WHERE edition_id=e.id ORDER BY sequence DESC LIMIT 1;
  SELECT provider_id,subject_id INTO reviewer_provider,reviewer_subject FROM public_answer_media_publicmediaaction WHERE edition_id=e.id AND action='REVIEW';
  IF NEW.sequence<>n+1 OR NEW.previous_digest<>coalesce(prior_digest,e.digest)
   OR EXISTS(SELECT 1 FROM public_answer_media_publicmediaaction WHERE edition_id=e.id AND action='WITHDRAW')
   OR (NEW.action='REVIEW' AND (n<>0 OR (NEW.provider_id=e.provider_id AND NEW.subject_id=e.subject_id)))
   OR (NEW.action='RELEASE' AND (n<>1 OR reviewer_subject IS NULL
      OR (NEW.provider_id=e.provider_id AND NEW.subject_id=e.subject_id)
      OR (NEW.provider_id=reviewer_provider AND NEW.subject_id=reviewer_subject)))
  THEN RAISE EXCEPTION 'recording independent release invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action='RELEASE' THEN
   IF NEW.valid_until<=clock_timestamp() OR NEW.valid_until>clock_timestamp()+interval '1 hour' THEN
    RAISE EXCEPTION 'recording finite release required' USING ERRCODE='23514'; END IF;
   IF e.transcript_id IS NOT NULL AND EXISTS(SELECT 1 FROM public_answer_media_transcriptaction WHERE transcript_id=e.transcript_id AND action='WITHDRAW') THEN
    RAISE EXCEPTION 'recording transcript withdrawn' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER pam_transcript_guard BEFORE INSERT OR UPDATE OR DELETE ON public_answer_media_recordingtranscript FOR EACH ROW EXECUTE FUNCTION pam_history_guard();
CREATE TRIGGER pam_transcript_action_guard BEFORE INSERT OR UPDATE OR DELETE ON public_answer_media_transcriptaction FOR EACH ROW EXECUTE FUNCTION pam_history_guard();
CREATE TRIGGER pam_edition_guard BEFORE INSERT OR UPDATE OR DELETE ON public_answer_media_publicmediaedition FOR EACH ROW EXECUTE FUNCTION pam_history_guard();
CREATE TRIGGER pam_media_action_guard BEFORE INSERT OR UPDATE OR DELETE ON public_answer_media_publicmediaaction FOR EACH ROW EXECUTE FUNCTION pam_history_guard();
"""

REVERSE = """
DROP TRIGGER pam_media_action_guard ON public_answer_media_publicmediaaction;
DROP TRIGGER pam_edition_guard ON public_answer_media_publicmediaedition;
DROP TRIGGER pam_transcript_action_guard ON public_answer_media_transcriptaction;
DROP TRIGGER pam_transcript_guard ON public_answer_media_recordingtranscript;
DROP FUNCTION pam_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("public_answer_media", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
