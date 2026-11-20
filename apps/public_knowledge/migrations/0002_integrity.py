"""Immutable curation, exact source/author bindings and independent release history."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION public_knowledge_series_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'public identity immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF (SELECT count(*) FROM public_knowledge_publicseries WHERE case_id=NEW.case_id)>=64
 OR NOT (
  (NEW.kind='SCHOLAR' AND NEW.author_provider<>'' AND NEW.author_subject<>'' AND NEW.publication_id IS NULL AND NEW.language='' AND NEW.external_id IS NULL)
  OR (NEW.kind='TOPIC' AND NEW.author_provider='' AND NEW.author_subject='' AND NEW.publication_id IS NULL AND NEW.language='' AND NEW.external_id IS NULL)
  OR (NEW.kind='PRESENTATION' AND NEW.author_provider='' AND NEW.author_subject='' AND NEW.publication_id IS NOT NULL AND NEW.language~'^[a-z]{2,3}(-[A-Z]{2})?$' AND NEW.external_id IS NULL
      AND EXISTS(SELECT 1 FROM experimental_publication_publicationedition WHERE id=NEW.publication_id AND case_id=NEW.case_id))
  OR (NEW.kind='LESSON' AND NEW.author_provider='' AND NEW.author_subject='' AND NEW.publication_id IS NULL AND NEW.language='' AND NEW.external_id IS NOT NULL)
 ) THEN RAISE EXCEPTION 'public identity binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER public_knowledge_series_guard BEFORE INSERT OR UPDATE OR DELETE ON public_knowledge_publicseries
 FOR EACH ROW EXECUTE FUNCTION public_knowledge_series_guard();

CREATE FUNCTION public_knowledge_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s public_knowledge_publicseries%ROWTYPE; c casework_case%ROWTYPE;
 p experimental_publication_publicationedition%ROWTYPE; answer_row casework_answerrevision%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'public revision immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO s FROM public_knowledge_publicseries WHERE id=NEW.series_id;
 SELECT * INTO c FROM casework_case WHERE id=s.case_id FOR UPDATE;
 SELECT * INTO p FROM experimental_publication_publicationedition WHERE id=NEW.publication_id;
 SELECT * INTO answer_row FROM casework_answerrevision WHERE id=p.answer_id;
 IF c.id IS NULL OR p.id IS NULL OR p.case_id<>c.id OR p.answer_id<>c.approved_answer_id
 OR c.stage<>'ANSWERED' OR p.evidence_version<>c.evidence_version
 OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version
 OR NEW.number<>(SELECT COALESCE(max(number),0)+1 FROM public_knowledge_publicrevision WHERE series_id=s.id)
 OR NEW.sha256!~'^[a-f0-9]{64}$' OR NEW.provider_id='' OR NEW.subject_id='' OR NEW.auth_epoch=''
 OR NOT EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=p.id AND action='APPROVE')
 OR EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=p.id AND action='WITHDRAW')
 OR EXISTS(SELECT 1 FROM experimental_publication_publicationedition e JOIN experimental_publication_publicationaction a ON a.edition_id=e.id
    WHERE e.case_id=c.id AND a.action='APPROVE' AND e.number>p.number)
 OR jsonb_typeof(NEW.payload)<>'object' THEN
  RAISE EXCEPTION 'public revision source invalid' USING ERRCODE='23514'; END IF;
 IF s.kind='SCHOLAR' THEN
  IF s.author_provider<>answer_row.provider_id OR s.author_subject<>answer_row.subject_id
   OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>2
   OR NOT NEW.payload ?& ARRAY['name','bio'] OR NEW.payload->>'name'!~'\S'
   OR char_length(NEW.payload->>'name')>160 OR char_length(NEW.payload->>'bio')>2000 THEN
   RAISE EXCEPTION 'public scholar invalid' USING ERRCODE='23514'; END IF;
 ELSIF s.kind='TOPIC' THEN
  IF (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>3
   OR NOT NEW.payload ?& ARRAY['title','introduction','parent_id'] OR NEW.payload->>'title'!~'\S'
   OR char_length(NEW.payload->>'title')>160 OR char_length(NEW.payload->>'introduction')>4000
   OR (NEW.payload->>'parent_id'<>'' AND NOT EXISTS(SELECT 1 FROM public_knowledge_publicrevision r JOIN public_knowledge_publicseries parent ON parent.id=r.series_id
      WHERE r.id::text=NEW.payload->>'parent_id' AND parent.kind='TOPIC' AND parent.case_id=c.id AND parent.id<>s.id)) THEN
   RAISE EXCEPTION 'public topic invalid' USING ERRCODE='23514'; END IF;
 ELSIF s.kind='PRESENTATION' THEN
  IF s.publication_id<>p.id OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>7
   OR NOT NEW.payload ?& ARRAY['title','question','body','description','scholar_id','topic_ids','relation_ids']
   OR NEW.payload->>'title'!~'\S' OR char_length(NEW.payload->>'title')>160
   OR char_length(NEW.payload->>'question')>8000 OR char_length(NEW.payload->>'body')>16000
   OR char_length(NEW.payload->>'description')>320 OR jsonb_typeof(NEW.payload->'topic_ids')<>'array'
   OR jsonb_array_length(NEW.payload->'topic_ids')>8
   OR jsonb_typeof(NEW.payload->'relation_ids')<>'array' OR jsonb_array_length(NEW.payload->'relation_ids')>8
   OR (s.language='ar' AND (NEW.payload->>'title'<>p.title OR NEW.payload->>'body'<>''))
   OR (s.language<>'ar' AND NEW.payload->>'body'!~'\S') THEN
   RAISE EXCEPTION 'public presentation invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>7
   OR NOT NEW.payload ?& ARRAY['title','summary','lesson_public_id','lesson_version','lesson_sha256','scholar_ids','topic_ids']
   OR NEW.payload->>'title'!~'\S' OR char_length(NEW.payload->>'title')>160 OR char_length(NEW.payload->>'summary')>4000
   OR NEW.payload->>'lesson_public_id'<>s.external_id::text OR NEW.payload->>'lesson_sha256'!~'^[a-f0-9]{64}$'
   OR NEW.payload->>'lesson_version'!~'^[1-9][0-9]{0,2}$'
   OR jsonb_typeof(NEW.payload->'scholar_ids')<>'array' OR jsonb_array_length(NEW.payload->'scholar_ids')>8
   OR jsonb_typeof(NEW.payload->'topic_ids')<>'array' OR jsonb_array_length(NEW.payload->'topic_ids')>8 THEN
   RAISE EXCEPTION 'public lesson invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER public_knowledge_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON public_knowledge_publicrevision
 FOR EACH ROW EXECUTE FUNCTION public_knowledge_revision_guard();

CREATE FUNCTION public_knowledge_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public_knowledge_publicrevision%ROWTYPE; reviewer public_knowledge_publicaction%ROWTYPE;
 d casework_casedecision%ROWTYPE; prior integer;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'public action immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public_knowledge_publicrevision WHERE id=NEW.revision_id;
 PERFORM 1 FROM casework_case c JOIN public_knowledge_publicseries s ON s.case_id=c.id WHERE s.id=r.series_id FOR UPDATE OF c;
 SELECT COALESCE(max(sequence),0) INTO prior FROM public_knowledge_publicaction WHERE revision_id=r.id;
 SELECT * INTO reviewer FROM public_knowledge_publicaction WHERE revision_id=r.id AND action='REVIEW';
 SELECT decision.* INTO d FROM casework_casedecision decision JOIN experimental_publication_publicationedition p ON p.decision_id=decision.id WHERE p.id=r.publication_id;
 IF NEW.sequence<>prior+1 OR NEW.content_sha256<>r.sha256 OR NEW.provider_id='' OR NEW.subject_id='' OR NEW.auth_epoch=''
 OR (NEW.action<>'RELEASE' AND (NEW.expires_at IS NOT NULL OR NEW.note!~'\S'))
 OR (NEW.action<>'RELEASE' AND NEW.requested_minutes<>0)
 OR (NEW.action='RELEASE' AND NEW.requested_minutes NOT IN (5,15,30,60))
 OR (NEW.action<>'REVOKE' AND NEW.related_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM public_knowledge_publicrevision WHERE series_id=r.series_id AND number>r.number)
 OR EXISTS(SELECT 1 FROM public_knowledge_publicaction WHERE revision_id=r.id AND action='WITHDRAW') THEN
  RAISE EXCEPTION 'public action invalid' USING ERRCODE='23514'; END IF;
 IF NEW.action='REVIEW' AND (prior<>0 OR (NEW.provider_id,NEW.subject_id)=(r.provider_id,r.subject_id)) THEN
  RAISE EXCEPTION 'independent public review required' USING ERRCODE='23514'; END IF;
 IF NEW.action='APPROVE' AND (reviewer.id IS NULL OR prior<>1
  OR (NEW.provider_id,NEW.subject_id)=(r.provider_id,r.subject_id)
  OR (NEW.provider_id,NEW.subject_id)=(reviewer.provider_id,reviewer.subject_id)
  OR (NEW.provider_id,NEW.subject_id)=(d.provider_id,d.subject_id)) THEN
  RAISE EXCEPTION 'independent public approval required' USING ERRCODE='23514'; END IF;
 IF NEW.action IN ('RELEASE','REVOKE') AND NOT EXISTS(SELECT 1 FROM public_knowledge_publicaction WHERE revision_id=r.id AND action='APPROVE') THEN
  RAISE EXCEPTION 'public approval required' USING ERRCODE='23514'; END IF;
 IF NEW.action='RELEASE' AND (NEW.expires_at IS NULL OR NEW.expires_at<=CURRENT_TIMESTAMP OR NEW.expires_at>CURRENT_TIMESTAMP+interval '1 hour') THEN
  RAISE EXCEPTION 'bounded explicit public lease required' USING ERRCODE='23514'; END IF;
 IF NEW.action='REVOKE' AND NOT EXISTS(SELECT 1 FROM public_knowledge_publicaction WHERE id=NEW.related_id AND revision_id=r.id AND action='RELEASE') THEN
  RAISE EXCEPTION 'exact public lease required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER public_knowledge_action_guard BEFORE INSERT OR UPDATE OR DELETE ON public_knowledge_publicaction
 FOR EACH ROW EXECUTE FUNCTION public_knowledge_action_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("public_knowledge", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER public_knowledge_action_guard ON public_knowledge_publicaction;
        DROP FUNCTION public_knowledge_action_guard();
        DROP TRIGGER public_knowledge_revision_guard ON public_knowledge_publicrevision;
        DROP FUNCTION public_knowledge_revision_guard();
        DROP TRIGGER public_knowledge_series_guard ON public_knowledge_publicseries;
        DROP FUNCTION public_knowledge_series_guard();
    """,
        )
    ]
