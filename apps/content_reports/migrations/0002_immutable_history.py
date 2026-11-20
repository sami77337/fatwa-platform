"""Preserve independent reports and enforce the audited human triage sequence."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION content_report_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c casework_case%ROWTYPE; k text;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'report submission immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 k := NEW.target->>'kind';
 IF c.id IS NULL OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version
 OR NEW.description !~ '\S' OR char_length(NEW.description)>2000
 OR char_length(NEW.evidence_note)>2000
 OR (SELECT count(*) FROM content_reports_contentreport WHERE case_id=c.id)>=128
 OR jsonb_typeof(NEW.target)<>'object'
 OR (SELECT count(*) FROM jsonb_object_keys(NEW.target))<>8
 OR NOT NEW.target ?& ARRAY['kind','identifier','version','sha256','answer_id',
                           'answer_revision','evidence_version','manifest_sha256']
 OR k NOT IN ('ANSWER','ANSWER_PART','PUBLICATION','TRANSCRIPT')
 OR NEW.target->>'sha256' !~ '^[a-f0-9]{64}$'
 OR NEW.target->>'version' !~ '^[1-9][0-9]{0,2}$'
 OR NEW.target->>'evidence_version' !~ '^[1-9][0-9]{0,2}$'
 OR (NEW.reporter_kind='REQUESTER' AND k NOT IN ('ANSWER','ANSWER_PART')) THEN
  RAISE EXCEPTION 'report binding invalid' USING ERRCODE='23514'; END IF;
 IF k IN ('ANSWER','ANSWER_PART','PUBLICATION') AND NOT EXISTS (
  SELECT 1 FROM casework_answerrevision a WHERE a.id::text=NEW.target->>'answer_id'
  AND a.case_id=c.id AND a.revision::text=NEW.target->>'answer_revision'
  AND a.evidence_version::text=NEW.target->>'evidence_version'
  AND a.id=c.approved_answer_id AND a.evidence_version=c.evidence_version
 ) THEN RAISE EXCEPTION 'report answer binding invalid' USING ERRCODE='23514'; END IF;
 IF k='ANSWER' AND NOT EXISTS (
  SELECT 1 FROM casework_answerrevision a WHERE a.id::text=NEW.target->>'identifier'
  AND a.id::text=NEW.target->>'answer_id' AND a.revision::text=NEW.target->>'version'
  AND a.text_sha256=NEW.target->>'sha256'
 ) THEN RAISE EXCEPTION 'report text binding invalid' USING ERRCODE='23514'; END IF;
 IF k='ANSWER_PART' AND NOT EXISTS (
  SELECT 1 FROM answer_media_answerpart p JOIN answer_media_answermanifest m ON m.answer_id=p.manifest_id
  WHERE p.id::text=NEW.target->>'identifier' AND m.answer_id::text=NEW.target->>'answer_id'
  AND p.ordinal>1 AND p.sha256=NEW.target->>'sha256' AND m.sha256=NEW.target->>'manifest_sha256'
 ) THEN RAISE EXCEPTION 'report part binding invalid' USING ERRCODE='23514'; END IF;
 IF k='PUBLICATION' AND NOT EXISTS (
  SELECT 1 FROM experimental_publication_publicationedition e
  WHERE e.id::text=NEW.target->>'identifier' AND e.case_id=c.id
  AND e.number::text=NEW.target->>'version' AND e.content_sha256=NEW.target->>'sha256'
  AND e.answer_id::text=NEW.target->>'answer_id'
 ) THEN RAISE EXCEPTION 'report edition binding invalid' USING ERRCODE='23514'; END IF;
 IF k='TRANSCRIPT' AND NOT EXISTS (
  SELECT 1 FROM transcript_case_links_transcriptlink t JOIN casework_caseevidence e ON e.id=t.evidence_id
  WHERE t.id::text=NEW.target->>'identifier' AND t.case_id=c.id
  AND e.version::text=NEW.target->>'version' AND e.version::text=NEW.target->>'evidence_version'
 ) THEN RAISE EXCEPTION 'report transcript binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER content_report_guard BEFORE INSERT OR UPDATE OR DELETE
 ON content_reports_contentreport FOR EACH ROW EXECUTE FUNCTION content_report_guard();

CREATE FUNCTION content_report_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r content_reports_contentreport%ROWTYPE; previous content_reports_reportevent%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'report review history immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM content_reports_contentreport WHERE id=NEW.report_id;
 PERFORM 1 FROM casework_case WHERE id=r.case_id FOR UPDATE;
 SELECT * INTO previous FROM content_reports_reportevent WHERE report_id=r.id ORDER BY sequence DESC LIMIT 1;
 IF NEW.sequence<>COALESCE(previous.sequence,0)+1 THEN
  RAISE EXCEPTION 'report review sequence invalid' USING ERRCODE='23514'; END IF;
 IF previous.id IS NULL THEN
  IF NEW.action<>'SUBMIT' OR NEW.state<>'OPEN' OR NEW.request_key<>r.request_key
  OR NEW.action_note<>'' OR NEW.verification_note<>'' OR NEW.related_report_id IS NOT NULL
  OR (r.reporter_kind='REQUESTER' AND (NEW.subject_id<>'' OR NEW.provider_id<>'' OR NEW.auth_epoch<>''))
  OR (r.reporter_kind='STAFF' AND (NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='')) THEN
   RAISE EXCEPTION 'report initial event invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.action_note !~ '\S'
  OR char_length(NEW.action_note)>2000 OR char_length(NEW.verification_note)>2000
  OR (NEW.action IN ('RESOLVE','DISMISS') AND NEW.verification_note !~ '\S')
  OR NOT (
   (NEW.action='START' AND previous.state='OPEN' AND NEW.state='IN_REVIEW')
   OR (NEW.action='RESOLVE' AND previous.state='IN_REVIEW' AND NEW.state='RESOLVED')
   OR (NEW.action='DISMISS' AND previous.state='IN_REVIEW' AND NEW.state='DISMISSED')
   OR (NEW.action='REOPEN' AND previous.state IN ('RESOLVED','DISMISSED') AND NEW.state='OPEN')
   OR (NEW.action='LINK' AND NEW.state=previous.state)
  ) THEN RAISE EXCEPTION 'report review transition invalid' USING ERRCODE='23514'; END IF;
  IF NEW.action='LINK' THEN
   IF NEW.related_report_id IS NULL OR NEW.related_report_id=r.id OR NOT EXISTS (
    SELECT 1 FROM content_reports_contentreport linked
    WHERE linked.id=NEW.related_report_id AND linked.case_id=r.case_id AND linked.target=r.target
   ) OR EXISTS (SELECT 1 FROM content_reports_reportevent e
     WHERE e.action='LINK' AND ((e.report_id=r.id AND e.related_report_id=NEW.related_report_id)
       OR (e.report_id=NEW.related_report_id AND e.related_report_id=r.id))) THEN
    RAISE EXCEPTION 'report repeat link invalid' USING ERRCODE='23514'; END IF;
  ELSIF NEW.related_report_id IS NOT NULL THEN
   RAISE EXCEPTION 'report unexpected link' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER content_report_event_guard BEFORE INSERT OR UPDATE OR DELETE
 ON content_reports_reportevent FOR EACH ROW EXECUTE FUNCTION content_report_event_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("content_reports", "0001_initial"),
        ("answer_media", "0004_answerpart_storage_backend_answerpart_storage_key_and_more"),
        ("experimental_publication", "0002_immutable_guards"),
        ("transcript_case_links", "0002_binding_guards"),
    ]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER content_report_event_guard ON content_reports_reportevent;
        DROP FUNCTION content_report_event_guard();
        DROP TRIGGER content_report_guard ON content_reports_contentreport;
        DROP FUNCTION content_report_guard();
    """,
        )
    ]
