"""Typed exact source pins, immutable versions and independent finite releases."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION pt_source_pin(pin_kind text, identifier uuid) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE result jsonb;
BEGIN
 IF pin_kind IN ('PROFILE','LESSON_METADATA') THEN
  SELECT jsonb_build_object('id',r.id,'sha256',r.sha256,'number',r.number,'case_id',s.case_id)
   INTO result FROM public_knowledge_publicrevision r JOIN public_knowledge_publicseries s ON s.id=r.series_id
   WHERE r.id=identifier AND s.kind=CASE WHEN pin_kind='PROFILE' THEN 'SCHOLAR' ELSE 'LESSON' END;
 ELSIF pin_kind='LIBRARY' THEN
  SELECT jsonb_build_object('id',v.id,'sha256',v.digest,'number',v.number,'case_id',i.case_id)
   INTO result FROM research_library_libraryversion v JOIN research_library_libraryitem i ON i.id=v.item_id WHERE v.id=identifier;
 ELSIF pin_kind='LESSON' THEN
  SELECT jsonb_build_object('id',v.id,'sha256',v.sha256,'number',v.number,'case_id',s.case_id)
   INTO result FROM scholarly_links_lessonversion v JOIN scholarly_links_lesson l ON l.id=v.lesson_id
   JOIN scholarly_links_lessonseries s ON s.id=l.series_id WHERE v.id=identifier;
 ELSIF pin_kind='SERIES' THEN
  SELECT jsonb_build_object('id',v.id,'sha256',v.sha256,'number',v.number,'case_id',s.case_id)
   INTO result FROM scholarly_links_seriesversion v JOIN scholarly_links_lessonseries s ON s.id=v.series_id WHERE v.id=identifier;
 ELSIF pin_kind='MEMBER' THEN
  SELECT jsonb_build_object('id',v.id,'sha256',v.digest,'number',v.number,'case_id',i.case_id)
   INTO result FROM public_teaching_teachingversion v JOIN public_teaching_teachingitem i ON i.id=v.item_id WHERE v.id=identifier AND i.kind='LESSON';
 END IF;
 RETURN result;
END $$;

CREATE FUNCTION pt_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'teaching identity immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF (SELECT count(*) FROM public_teaching_teachingitem WHERE case_id=NEW.case_id)>=64
  OR NEW.public_id IN (NEW.id,NEW.case_id,NEW.external_id)
  OR (NEW.kind='SCHOLAR_MATERIAL') IS DISTINCT FROM (NEW.secondary_id IS NOT NULL) THEN
  RAISE EXCEPTION 'teaching identity bound or kind invalid' USING ERRCODE='23514'; END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER pt_item_guard BEFORE INSERT OR UPDATE OR DELETE ON public_teaching_teachingitem FOR EACH ROW EXECUTE FUNCTION pt_item_guard();

CREATE FUNCTION pt_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; item public_teaching_teachingitem%ROWTYPE; c casework_case%ROWTYPE;
 v public_teaching_teachingversion%ROWTYPE; prior public_teaching_teachingversion%ROWTYPE;
 meta public_knowledge_publicrevision%ROWTYPE; prof public_knowledge_publicrevision%ROWTYPE;
 lib research_library_libraryversion%ROWTYPE; lesson scholarly_links_lessonversion%ROWTYPE;
 series scholarly_links_seriesversion%ROWTYPE; actual_part answer_media_answerpart%ROWTYPE;
 member jsonb; member_row public_teaching_teachingversion%ROWTYPE; member_lesson uuid;
 n integer; previous text; reviewer_provider text; reviewer_subject text;
 expected jsonb; last_position integer:=0; position integer;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'teaching history immutable' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 IF TG_TABLE_NAME='public_teaching_teachingaction' THEN
  IF NEW.valid_until IS NOT NULL THEN
   body:=jsonb_set(body,'{valid_until}',to_jsonb(to_char(NEW.valid_until AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
  END IF;
 END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM body
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.request_sha256 !~ '^[a-f0-9]{64}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR btrim(NEW.note)='' OR length(NEW.note)>1000 THEN
  RAISE EXCEPTION 'teaching seal invalid' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(546131,1);
 IF TG_TABLE_NAME='public_teaching_teachingversion' THEN
  SELECT * INTO item FROM public_teaching_teachingitem WHERE id=NEW.item_id;
 ELSE
  SELECT * INTO v FROM public_teaching_teachingversion WHERE id=NEW.version_id;
  SELECT * INTO item FROM public_teaching_teachingitem WHERE id=v.item_id;
 END IF;
 SELECT * INTO c FROM casework_case WHERE id=item.case_id FOR UPDATE;
 IF c.id IS NULL OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version THEN
  RAISE EXCEPTION 'teaching canonical pins changed' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='public_teaching_teachingversion' THEN
  SELECT * INTO prior FROM public_teaching_teachingversion WHERE item_id=item.id ORDER BY number DESC LIMIT 1;
  IF NEW.number<>coalesce(prior.number,0)+1 OR NEW.previous_digest<>coalesce(prior.digest,repeat('0',64))
   OR btrim(NEW.title)='' OR length(NEW.title)>160 OR length(NEW.summary)>2000
   OR length(NEW.topic)>160 OR length(NEW.attribution)>1000
   OR jsonb_typeof(NEW.teacher_labels) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.teacher_labels)>8
   OR jsonb_typeof(NEW.members) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.members)>16
   OR jsonb_typeof(NEW.source_pins) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'teaching version invalid' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.teacher_labels) x WHERE jsonb_typeof(x) IS DISTINCT FROM 'string' OR btrim(x#>>'{}')='' OR length(x#>>'{}')>120)
   OR (SELECT count(*) FROM jsonb_array_elements(NEW.teacher_labels))<>(SELECT count(DISTINCT x) FROM jsonb_array_elements(NEW.teacher_labels) x) THEN
   RAISE EXCEPTION 'teaching teacher labels invalid' USING ERRCODE='23514'; END IF;
  IF item.kind='SCHOLAR_MATERIAL' THEN
   SELECT * INTO prof FROM public_knowledge_publicrevision WHERE id=NEW.profile_id;
   SELECT * INTO lib FROM research_library_libraryversion WHERE id=NEW.library_version_id;
   expected:=jsonb_build_object('profile',pt_source_pin('PROFILE',NEW.profile_id),'library',pt_source_pin('LIBRARY',NEW.library_version_id));
   IF prof.id IS NULL OR lib.id IS NULL OR pt_source_pin('PROFILE',NEW.profile_id) IS NULL
    OR prof.series_id<>item.external_id OR lib.item_id<>item.secondary_id
    OR NEW.lesson_metadata_id IS NOT NULL OR NEW.lesson_version_id IS NOT NULL OR NEW.series_version_id IS NOT NULL
    OR NEW.members<>'[]'::jsonb OR NEW.teacher_labels<>'[]'::jsonb OR NEW.topic<>'' OR btrim(NEW.attribution)=''
    OR NEW.source_pins IS DISTINCT FROM expected THEN
    RAISE EXCEPTION 'teaching exact attribution invalid' USING ERRCODE='23514'; END IF;
  ELSIF item.kind='LESSON' THEN
   SELECT * INTO meta FROM public_knowledge_publicrevision WHERE id=NEW.lesson_metadata_id;
   SELECT * INTO lesson FROM scholarly_links_lessonversion WHERE id=NEW.lesson_version_id;
   SELECT * INTO series FROM scholarly_links_seriesversion WHERE id=NEW.series_version_id;
   SELECT * INTO actual_part FROM answer_media_answerpart WHERE id=lesson.source_part_id;
   expected:=jsonb_build_object('metadata',pt_source_pin('LESSON_METADATA',NEW.lesson_metadata_id),
    'lesson',pt_source_pin('LESSON',NEW.lesson_version_id),'series',pt_source_pin('SERIES',NEW.series_version_id),'part',lesson.source_snapshot);
   IF meta.id IS NULL OR lesson.id IS NULL OR series.id IS NULL OR actual_part.kind IS DISTINCT FROM 'AUDIO'
    OR pt_source_pin('LESSON_METADATA',NEW.lesson_metadata_id) IS NULL OR meta.series_id<>item.external_id
    OR lesson.series_version_id<>series.id OR (meta.payload->>'lesson_sha256') IS DISTINCT FROM lesson.sha256
    OR (meta.payload->>'lesson_version') IS DISTINCT FROM lesson.number::text
    OR (meta.payload->>'lesson_public_id') IS DISTINCT FROM (SELECT public_id::text FROM scholarly_links_lesson WHERE id=lesson.lesson_id)
    OR NEW.profile_id IS NOT NULL OR NEW.library_version_id IS NOT NULL OR NEW.members<>'[]'::jsonb
    OR NEW.teacher_labels<>'[]'::jsonb OR NEW.topic<>'' OR NEW.attribution<>''
    OR NEW.source_pins IS DISTINCT FROM expected
    OR NOT EXISTS(SELECT 1 FROM casework_casedecision WHERE answer_id=actual_part.manifest_id AND action='APPROVE') THEN
    RAISE EXCEPTION 'teaching exact original lesson invalid' USING ERRCODE='23514'; END IF;
  ELSIF item.kind='SERIES' THEN
   SELECT * INTO series FROM scholarly_links_seriesversion WHERE id=NEW.series_version_id;
   expected:=jsonb_build_object('series',pt_source_pin('SERIES',NEW.series_version_id));
   IF series.id IS NULL OR item.external_id IS DISTINCT FROM (SELECT public_id FROM scholarly_links_lessonseries WHERE id=series.series_id)
    OR NEW.profile_id IS NOT NULL OR NEW.library_version_id IS NOT NULL OR NEW.lesson_metadata_id IS NOT NULL OR NEW.lesson_version_id IS NOT NULL
    OR NEW.attribution<>'' OR NEW.source_pins IS DISTINCT FROM expected OR jsonb_array_length(NEW.members)=0
    OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.teacher_labels) label WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(series.teachers) teacher WHERE teacher->>'name'=label)) THEN
    RAISE EXCEPTION 'teaching exact series invalid' USING ERRCODE='23514'; END IF;
   FOR member IN SELECT value FROM jsonb_array_elements(NEW.members) LOOP
    IF jsonb_typeof(member) IS DISTINCT FROM 'object' OR member->>'id' IS NULL THEN
     RAISE EXCEPTION 'teaching series member invalid' USING ERRCODE='23514'; END IF;
    SELECT * INTO member_row FROM public_teaching_teachingversion WHERE id::text=member->>'id';
    IF member_row.id IS NULL OR member IS DISTINCT FROM pt_source_pin('MEMBER',member_row.id)
     OR NOT EXISTS(SELECT 1 FROM public_teaching_teachingaction WHERE version_id=member_row.id AND action='RELEASE' AND valid_until>clock_timestamp())
     OR EXISTS(SELECT 1 FROM public_teaching_teachingaction WHERE version_id=member_row.id AND action='WITHDRAW') THEN
     RAISE EXCEPTION 'teaching exact released member required' USING ERRCODE='23514'; END IF;
    SELECT lesson_id INTO member_lesson FROM scholarly_links_lessonversion WHERE id=member_row.lesson_version_id;
    SELECT ordinality INTO position FROM jsonb_array_elements_text(series.lesson_order) WITH ORDINALITY x(value,ordinality) WHERE value=member_lesson::text;
    IF position IS NULL OR position<=last_position THEN
     RAISE EXCEPTION 'teaching documented order invalid' USING ERRCODE='23514'; END IF;
    last_position:=position;
   END LOOP;
  ELSE RAISE EXCEPTION 'teaching kind invalid' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT count(*),max(sequence) INTO n,position FROM public_teaching_teachingaction WHERE version_id=v.id;
  SELECT digest INTO previous FROM public_teaching_teachingaction WHERE version_id=v.id ORDER BY sequence DESC LIMIT 1;
  SELECT provider_id,subject_id INTO reviewer_provider,reviewer_subject FROM public_teaching_teachingaction WHERE version_id=v.id AND action='REVIEW';
  IF NEW.sequence<>n+1 OR NEW.previous_digest<>coalesce(previous,v.digest)
   OR EXISTS(SELECT 1 FROM public_teaching_teachingaction WHERE version_id=v.id AND action='WITHDRAW')
   OR (NEW.action<>'WITHDRAW' AND EXISTS(SELECT 1 FROM public_teaching_teachingversion WHERE item_id=v.item_id AND number>v.number))
   OR (NEW.action='REVIEW' AND (n<>0 OR (NEW.provider_id,NEW.subject_id)=(v.provider_id,v.subject_id)))
   OR (NEW.action='APPROVE' AND (n<>1 OR reviewer_subject IS NULL OR (NEW.provider_id,NEW.subject_id) IN ((v.provider_id,v.subject_id),(reviewer_provider,reviewer_subject))))
   OR (NEW.action='RELEASE' AND (n<>2 OR NOT EXISTS(SELECT 1 FROM public_teaching_teachingaction WHERE version_id=v.id AND action='APPROVE')
    OR (NEW.provider_id,NEW.subject_id) IN ((v.provider_id,v.subject_id),(reviewer_provider,reviewer_subject)))) THEN
   RAISE EXCEPTION 'teaching independent decision invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action='RELEASE' THEN
   IF NEW.valid_until<=clock_timestamp() OR NEW.valid_until>clock_timestamp()+interval '1 hour' THEN
    RAISE EXCEPTION 'teaching finite release required' USING ERRCODE='23514'; END IF;
   IF item.kind='SERIES' AND EXISTS(SELECT 1 FROM jsonb_array_elements(v.members) m WHERE
    NOT EXISTS(SELECT 1 FROM public_teaching_teachingaction a WHERE a.version_id::text=m->>'id' AND a.action='RELEASE' AND a.valid_until>clock_timestamp())
    OR EXISTS(SELECT 1 FROM public_teaching_teachingaction a WHERE a.version_id::text=m->>'id' AND a.action='WITHDRAW')) THEN
    RAISE EXCEPTION 'teaching series member unavailable' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.created_at:=statement_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER pt_version_guard BEFORE INSERT OR UPDATE OR DELETE ON public_teaching_teachingversion FOR EACH ROW EXECUTE FUNCTION pt_history_guard();
CREATE TRIGGER pt_action_guard BEFORE INSERT OR UPDATE OR DELETE ON public_teaching_teachingaction FOR EACH ROW EXECUTE FUNCTION pt_history_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS pt_action_guard ON public_teaching_teachingaction;
DROP TRIGGER IF EXISTS pt_version_guard ON public_teaching_teachingversion;
DROP TRIGGER IF EXISTS pt_item_guard ON public_teaching_teachingitem;
DROP FUNCTION IF EXISTS pt_history_guard();
DROP FUNCTION IF EXISTS pt_item_guard();
DROP FUNCTION IF EXISTS pt_source_pin(text,uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("public_teaching", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
