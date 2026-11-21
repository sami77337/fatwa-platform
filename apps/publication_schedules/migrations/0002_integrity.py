from django.db import migrations

SQL = r"""
CREATE FUNCTION ps_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; e experimental_publication_publicationedition%ROWTYPE;
 d casework_casedecision%ROWTYPE; r experimental_publication_publicationaction%ROWTYPE;
 s publication_schedules_publicationschedule%ROWTYPE;
 a experimental_publication_publicationaction%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'publication schedule history immutable' USING ERRCODE='23514'; END IF;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 IF TG_TABLE_NAME='publication_schedules_publicationschedule' THEN
  body:=jsonb_set(body,'{scheduled_at}',to_jsonb(to_char(NEW.scheduled_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
 END IF;
 IF NEW.canonical_payload::jsonb IS DISTINCT FROM body OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$' THEN
  RAISE EXCEPTION 'publication schedule seal invalid' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='publication_schedules_publicationschedule' THEN
  SELECT * INTO e FROM experimental_publication_publicationedition WHERE id=NEW.edition_id;
  PERFORM 1 FROM casework_case WHERE id=e.case_id FOR UPDATE;
  SELECT * INTO d FROM casework_casedecision WHERE id=e.decision_id;
  SELECT * INTO r FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action='REVIEW';
  IF e.id IS NULL OR r.id IS NULL OR NEW.target<>'WEBSITE_PREVIEW' OR NEW.edition_sha256 IS DISTINCT FROM e.content_sha256
   OR NEW.source_sha256 !~ '^[a-f0-9]{64}$' OR NEW.scheduled_at<=NEW.created_at OR NEW.scheduled_at>NEW.created_at+interval '30 days'
   OR length(NEW.reason) NOT BETWEEN 1 AND 500 OR btrim(NEW.reason)=''
   OR (NEW.provider_id,NEW.subject_id) IN ((e.provider_id,e.subject_id),(d.provider_id,d.subject_id),(r.provider_id,r.subject_id))
   OR EXISTS(SELECT 1 FROM experimental_publication_publicationaction WHERE edition_id=e.id AND action IN ('APPROVE','WITHDRAW'))
   OR EXISTS(SELECT 1 FROM publication_schedules_publicationschedule p LEFT JOIN publication_schedules_scheduleoutcome o ON o.schedule_id=p.id WHERE p.edition_id=e.id AND o.id IS NULL)
  THEN RAISE EXCEPTION 'publication schedule source or timing invalid' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO s FROM publication_schedules_publicationschedule WHERE id=NEW.schedule_id FOR UPDATE;
  IF s.id IS NULL OR NEW.actor_kind NOT IN ('STAFF','WORKER') OR length(NEW.reason) NOT BETWEEN 1 AND 128
   OR (NEW.actor_kind='WORKER' AND NEW.action<>'HOLD')
   OR (NEW.action<>'PUBLISHED' AND NEW.publication_action_id IS NOT NULL) THEN
   RAISE EXCEPTION 'publication schedule outcome invalid' USING ERRCODE='23514';
  END IF;
  IF NEW.action='PUBLISHED' THEN
   SELECT * INTO a FROM experimental_publication_publicationaction WHERE id=NEW.publication_action_id;
   IF NEW.actor_kind<>'STAFF' OR s.scheduled_at>NEW.created_at OR a.id IS NULL OR a.edition_id<>s.edition_id OR a.action<>'APPROVE'
    OR (NEW.provider_id,NEW.subject_id,NEW.auth_epoch) IS DISTINCT FROM (s.provider_id,s.subject_id,s.auth_epoch)
    OR (a.provider_id,a.subject_id,a.auth_epoch) IS DISTINCT FROM (s.provider_id,s.subject_id,s.auth_epoch) THEN
    RAISE EXCEPTION 'publication schedule exact approval required' USING ERRCODE='23514';
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ps_schedule_guard BEFORE INSERT OR UPDATE OR DELETE ON publication_schedules_publicationschedule FOR EACH ROW EXECUTE FUNCTION ps_history_guard();
CREATE TRIGGER ps_outcome_guard BEFORE INSERT OR UPDATE OR DELETE ON publication_schedules_scheduleoutcome FOR EACH ROW EXECUTE FUNCTION ps_history_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("publication_schedules", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER ps_outcome_guard ON publication_schedules_scheduleoutcome; DROP TRIGGER ps_schedule_guard ON publication_schedules_publicationschedule; DROP FUNCTION ps_history_guard();",
        )
    ]
