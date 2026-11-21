"""Append-only, ordered, sealed administrative revisions with a closed action matrix."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION ps_rule_valid(value jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE s jsonb; r jsonb; a text; k text; keys text[]; section text; pair record;
BEGIN
 IF jsonb_typeof(value) IS DISTINCT FROM 'object' OR value-ARRAY['scope','effect']<>'{}'::jsonb
  OR NOT value ?& ARRAY['scope','effect'] OR jsonb_typeof(value->'effect') IS DISTINCT FROM 'string' OR value->>'effect' NOT IN ('ALLOW','DENY') THEN RETURN false; END IF;
 s:=value->'scope'; r:=s->'resource'; a:=s->>'action'; k:=r->>'kind';
 IF jsonb_typeof(s) IS DISTINCT FROM 'object' OR s-ARRAY['domain','case_ref','action','resource']<>'{}'::jsonb
  OR NOT s ?& ARRAY['domain','case_ref','action','resource'] OR s->>'domain' IS DISTINCT FROM 'OPERATIONAL'
  OR jsonb_typeof(s->'case_ref') IS DISTINCT FROM 'string' OR jsonb_typeof(s->'action') IS DISTINCT FROM 'string'
  OR (s->>'case_ref') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR jsonb_typeof(r->'kind') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
 section:=CASE a
  WHEN 'READ_QUEUE' THEN 'queue' WHEN 'READ_CASE' THEN 'case' WHEN 'READ_METADATA' THEN 'metadata'
  WHEN 'READ_DELIVERY' THEN 'delivery' WHEN 'READ_PUBLICATION' THEN 'publication'
  WHEN 'READ_TRANSCRIPT' THEN 'transcript' WHEN 'READ_CAPABILITY' THEN 'capability'
  WHEN 'READ_INTERNAL_NOTES' THEN 'internal_notes' WHEN 'ADD_INTERNAL_NOTE' THEN 'internal_notes'
  WHEN 'EDIT_TAGS' THEN 'metadata' WHEN 'EDIT_QUESTION_TYPES' THEN 'metadata'
  WHEN 'READ_LESSON_LINKS' THEN 'lesson_links' WHEN 'READ_TRANSCRIPT_EDITOR' THEN 'transcript_editor'
  WHEN 'READ_PUBLICATION_MANAGER' THEN 'publication_manager' ELSE NULL END;
 keys:=ARRAY['kind','case_id'];
 IF section IS NOT NULL THEN
  IF k IS DISTINCT FROM 'CASE_OPERATIONAL_SECTION' OR r->>'section' IS DISTINCT FROM section THEN RETURN false; END IF;
  keys:=keys||ARRAY['section'];
 ELSIF a IN ('READ_CLASSIFICATION','BIND_CLASSIFICATION') AND k='CASE_CLASSIFICATION_VERSION' THEN
  keys:=keys||ARRAY['tree_case_id','tree_id','version_id','digest'];
 ELSIF a IN ('READ_COORDINATION','SET_PRIMARY','CLEAR_PRIMARY','SET_PRIORITY') AND k='CASE_COORDINATION' THEN
  IF a='SET_PRIMARY' THEN keys:=keys||ARRAY['target','target_epoch'];
  ELSIF a='CLEAR_PRIMARY' THEN keys:=keys||ARRAY['target'];
  ELSIF a='SET_PRIORITY' THEN keys:=keys||ARRAY['priority','label','rank','policy_sha256']; END IF;
 ELSIF a IN ('READ_OPERATIONAL_LESSON','PROPOSE_LESSON_LINK') AND k='CASE_LESSON_VERSION' THEN
  keys:=keys||ARRAY['target_case_id','version_id','version_sha256'];
 ELSIF a IN ('READ_LESSON_LINK','APPROVE_LESSON_LINK','REJECT_LESSON_LINK','WITHDRAW_LESSON_LINK') AND k='CASE_LESSON_LINK' THEN
  keys:=keys||ARRAY['target_case_id','version_id','version_sha256','link_id','link_sha256'];
 ELSIF a IN ('READ_RECORDING_TRANSCRIPT','EDIT_RECORDING_TRANSCRIPT','READ_RECORDING_AUDIO') AND k='CASE_RECORDING_SOURCE' THEN
  keys:=keys||ARRAY['part_id','part_sha256'];
 ELSIF a IN ('READ_RECORDING_TRANSCRIPT','EDIT_RECORDING_TRANSCRIPT','REVIEW_RECORDING_TRANSCRIPT','WITHDRAW_RECORDING_TRANSCRIPT') AND k='CASE_RECORDING_TRANSCRIPT' THEN
  keys:=keys||ARRAY['part_id','part_sha256','transcript_id','transcript_digest'];
 ELSIF a IN ('READ_PUBLICATION_EDITION','REVIEW_PUBLICATION_EDITION','APPROVE_PUBLICATION_EDITION','WITHDRAW_PUBLICATION_EDITION') AND k='CASE_PUBLICATION_EDITION' THEN
  keys:=keys||ARRAY['edition_id','content_sha256','answer_id','decision_id','evidence_version'];
 ELSE RETURN false; END IF;
 IF NOT r ?& keys OR r-keys<>'{}'::jsonb THEN RETURN false; END IF;
 FOR pair IN SELECT * FROM jsonb_each(r) LOOP
  IF right(pair.key,3)='_id' AND (
   jsonb_typeof(pair.value) IS DISTINCT FROM 'string' OR pair.value#>>'{}' !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
  ) THEN RETURN false; END IF;
  IF (right(pair.key,7)='_sha256' OR right(pair.key,7)='_digest' OR pair.key='digest') AND (
   jsonb_typeof(pair.value) IS DISTINCT FROM 'string' OR pair.value#>>'{}' !~ '^[a-f0-9]{64}$'
  ) THEN RETURN false; END IF;
  IF pair.key IN ('target','target_epoch','priority') AND (
   jsonb_typeof(pair.value) IS DISTINCT FROM 'string' OR pair.value#>>'{}' !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  ) THEN RETURN false; END IF;
  IF pair.key IN ('rank','evidence_version') AND (
   jsonb_typeof(pair.value) IS DISTINCT FROM 'number' OR pair.value#>>'{}' !~ '^[0-9]+$'
  ) THEN RETURN false; END IF;
  IF pair.key='label' AND (
   jsonb_typeof(pair.value) IS DISTINCT FROM 'string' OR btrim(pair.value#>>'{}')=''
   OR length(pair.value#>>'{}')>128
  ) THEN RETURN false; END IF;
  IF pair.key='rank' AND (pair.value#>>'{}')::numeric NOT BETWEEN 0 AND 100 THEN RETURN false; END IF;
  IF pair.key='evidence_version' AND (pair.value#>>'{}')::numeric<1 THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION ps_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous permission_sets_permissionrevision%ROWTYPE;
 reverted permission_sets_permissionrevision%ROWTYPE; own permission_sets_permissionrevision%ROWTYPE;
 rules jsonb; item jsonb; selected text; duplicate_count integer; body jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'permission history immutable' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(401404,1);
 SELECT * INTO previous FROM permission_sets_permissionrevision
  WHERE kind=NEW.kind AND provider_id=NEW.provider_id AND scope_key=NEW.scope_key ORDER BY number DESC LIMIT 1;
 body:=to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at'];
 IF NEW.valid_until IS NOT NULL THEN
  body:=jsonb_set(body,'{valid_until}',to_jsonb(to_char(NEW.valid_until AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
 END IF;
 IF NEW.number<>coalesce(previous.number,0)+1
  OR NEW.previous_digest<>coalesce(previous.digest,repeat('0',64))
  OR NEW.canonical_payload::jsonb IS DISTINCT FROM body
  OR NEW.digest<>encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')
  OR NEW.provider_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.actor_provider_id<>NEW.provider_id
  OR NEW.actor_subject_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  OR NEW.actor_auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
  OR NEW.request_digest !~ '^[a-f0-9]{64}$' OR NEW.policy_digest !~ '^[a-f0-9]{64}$'
  OR btrim(NEW.note)='' OR length(NEW.note)>1000
  OR NEW.valid_until IS NULL OR NEW.valid_until<=statement_timestamp()
  OR NEW.valid_until>statement_timestamp()+interval '1 hour'
  OR jsonb_typeof(NEW.definition) IS DISTINCT FROM 'object'
  OR jsonb_typeof(NEW.context) IS DISTINCT FROM 'object'
  OR jsonb_typeof(NEW.context->'policy') IS DISTINCT FROM 'string'
  OR jsonb_typeof(NEW.context->'ledger') IS DISTINCT FROM 'string'
  OR NEW.context->>'policy' IS DISTINCT FROM NEW.policy_digest
  OR (NEW.context->>'ledger') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'permission revision or seal invalid' USING ERRCODE='23514';
 END IF;
 IF (previous.id IS NULL)<>(NEW.change='CREATE')
  OR NEW.change='CREATE' AND NEW.state<>'ACTIVE'
  OR NEW.change='REPLACE' AND NEW.state<>'ACTIVE'
  OR NEW.change='DISABLE' AND (NEW.state<>'DISABLED' OR NEW.definition IS DISTINCT FROM previous.definition)
  OR (NEW.change='REVERT')<>(NEW.reverted_from_id IS NOT NULL) THEN
  RAISE EXCEPTION 'permission transition invalid' USING ERRCODE='23514';
 END IF;
 IF NEW.change='REVERT' THEN
  SELECT * INTO reverted FROM permission_sets_permissionrevision WHERE id=NEW.reverted_from_id;
  IF reverted.id IS NULL OR reverted.kind<>NEW.kind OR reverted.provider_id<>NEW.provider_id
   OR reverted.scope_key<>NEW.scope_key OR reverted.number>=previous.number
   OR reverted.definition IS DISTINCT FROM NEW.definition OR reverted.state<>NEW.state THEN
   RAISE EXCEPTION 'permission revert invalid' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.kind='SET' THEN
  IF NEW.scope_key !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
   OR NEW.target_role<>'' OR NEW.target_auth_epoch<>'' OR NEW.target_scope_digest<>''
   OR NOT NEW.definition ?& ARRAY['title','rules'] OR NEW.definition-ARRAY['title','rules']<>'{}'::jsonb
   OR jsonb_typeof(NEW.definition->'title') IS DISTINCT FROM 'string' OR btrim(NEW.definition->>'title')=''
   OR length(NEW.definition->>'title')>160 THEN
   RAISE EXCEPTION 'permission template invalid' USING ERRCODE='23514';
  END IF;
  SELECT * INTO own FROM permission_sets_permissionrevision WHERE kind='USER'
   AND provider_id=NEW.provider_id AND scope_key=NEW.actor_subject_id ORDER BY number DESC LIMIT 1;
  IF own.definition->'sets' ? NEW.scope_key THEN
   RAISE EXCEPTION 'permission self template change denied' USING ERRCODE='23514';
  END IF;
  rules:=NEW.definition->'rules';
 ELSE
  IF NEW.scope_key=NEW.actor_subject_id
   OR NEW.scope_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
   OR NEW.target_role NOT IN ('MUFTI','ORGANIZER_ADMIN','ORGANIZER')
   OR NEW.target_auth_epoch !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'
   OR NEW.target_scope_digest !~ '^[a-f0-9]{64}$'
   OR NOT NEW.definition ?& ARRAY['sets','overrides'] OR NEW.definition-ARRAY['sets','overrides']<>'{}'::jsonb
   OR jsonb_typeof(NEW.definition->'sets') IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.definition->'sets')>16 THEN
   RAISE EXCEPTION 'permission user configuration invalid' USING ERRCODE='23514';
  END IF;
  FOR item IN SELECT * FROM jsonb_array_elements(NEW.definition->'sets') LOOP
   selected:=item#>>'{}';
   IF jsonb_typeof(item) IS DISTINCT FROM 'string' OR NOT EXISTS (
    SELECT 1 FROM permission_sets_permissionrevision WHERE kind='SET' AND provider_id=NEW.provider_id AND scope_key=selected
   ) THEN RAISE EXCEPTION 'permission selected template unavailable' USING ERRCODE='23514'; END IF;
  END LOOP;
  SELECT count(*)-count(DISTINCT x) INTO duplicate_count FROM jsonb_array_elements(NEW.definition->'sets') x;
  IF duplicate_count<>0 THEN RAISE EXCEPTION 'permission duplicate template' USING ERRCODE='23514'; END IF;
  rules:=NEW.definition->'overrides';
 END IF;
 IF jsonb_typeof(rules) IS DISTINCT FROM 'array' OR jsonb_array_length(rules)>64 THEN
  RAISE EXCEPTION 'permission rules invalid' USING ERRCODE='23514';
 END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(rules) LOOP
  IF ps_rule_valid(item) IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'permission rule outside operational matrix' USING ERRCODE='23514';
  END IF;
 END LOOP;
 SELECT count(*)-count(DISTINCT x->'scope') INTO duplicate_count FROM jsonb_array_elements(rules) x;
 IF duplicate_count<>0 THEN RAISE EXCEPTION 'permission duplicate rule' USING ERRCODE='23514'; END IF;
 NEW.created_at:=statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER ps_revision_guard BEFORE INSERT OR UPDATE OR DELETE
 ON permission_sets_permissionrevision FOR EACH ROW EXECUTE FUNCTION ps_revision_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("permission_sets", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER IF EXISTS ps_revision_guard ON permission_sets_permissionrevision;"
            "DROP FUNCTION IF EXISTS ps_revision_guard(); DROP FUNCTION IF EXISTS ps_rule_valid(jsonb);",
        )
    ]
