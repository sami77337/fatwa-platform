from django.db import migrations

SQL = r"""
CREATE FUNCTION rs_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    previous record;
    target_previous record;
    expected jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'suppression_history_immutable';
    END IF;
    PERFORM pg_advisory_xact_lock(387,387);
    SELECT * INTO previous FROM record_suppression_suppressionevent ORDER BY sequence DESC LIMIT 1;
    SELECT * INTO target_previous FROM record_suppression_suppressionevent
      WHERE target_kind=NEW.target_kind AND target_id=NEW.target_id ORDER BY version DESC LIMIT 1;
    IF NEW.sequence IS DISTINCT FROM COALESCE(previous.sequence,0)+1
       OR NEW.previous_digest IS DISTINCT FROM COALESCE(previous.digest,repeat('0',64))
       OR (previous.id IS NOT NULL AND NEW.ledger_id IS DISTINCT FROM previous.ledger_id)
       OR NEW.version IS DISTINCT FROM COALESCE(target_previous.version,0)+1
       OR NEW.previous_state IS DISTINCT FROM COALESCE(target_previous.state,'ACTIVE')
       OR (target_previous.id IS NOT NULL AND
           (NEW.source_digest IS DISTINCT FROM target_previous.source_digest
            OR NEW.case_id IS DISTINCT FROM target_previous.case_id)) THEN
        RAISE EXCEPTION 'suppression_history_discontinuity';
    END IF;
    IF NOT ((NEW.previous_state IN ('ACTIVE','RESTORED') AND NEW.state='SOFT_DELETED' AND NEW.action='SOFT_DELETE')
            OR (NEW.previous_state='SOFT_DELETED' AND NEW.state='RESTORED' AND NEW.action='RESTORE')) IS TRUE THEN
        RAISE EXCEPTION 'suppression_transition_invalid';
    END IF;
    IF NOT (NEW.target_kind IN ('CASE','ANSWER','ATTACHMENT','ANSWER_PART','LIBRARY_VERSION',
        'SOURCE_VERSION','SOURCE_RECEIPT','TRANSCRIPT_LINK','RECORDING_TRANSCRIPT','PUBLICATION',
        'PUBLIC_MEDIA','PUBLIC_KNOWLEDGE','PUBLIC_COLLECTION','PUBLIC_TEACHING','LESSON_VERSION',
        'KNOWLEDGE_REVISION','SERIES_VERSION')) IS TRUE
       OR NEW.target_kind='CASE' AND NEW.case_id IS DISTINCT FROM NEW.target_id
       OR NOT (NEW.source_digest ~ '^[0-9a-f]{64}$' AND NEW.previous_digest ~ '^[0-9a-f]{64}$'
           AND NEW.reason_sha256 ~ '^[0-9a-f]{64}$' AND NEW.digest ~ '^[0-9a-f]{64}$') IS TRUE
       OR NOT (length(btrim(NEW.provider_id))>0 AND length(btrim(NEW.subject_id))>0
           AND length(btrim(NEW.auth_epoch))>0 AND length(btrim(NEW.applied_provider_id))>0
           AND length(btrim(NEW.applied_subject_id))>0 AND length(btrim(NEW.applied_auth_epoch))>0) IS TRUE
       OR NOT (length(NEW.reason)<=1000 AND length(NEW.recovery_reason)<=1000) IS TRUE
       OR NOT ((NEW.recovered AND NEW.reason='' AND length(btrim(NEW.recovery_reason))>0)
           OR (NOT NEW.recovered AND length(btrim(NEW.reason))>0 AND NEW.recovery_reason=''
               AND NEW.provider_id=NEW.applied_provider_id AND NEW.subject_id=NEW.applied_subject_id
               AND NEW.role=NEW.applied_role AND NEW.auth_epoch=NEW.applied_auth_epoch)) IS TRUE
       OR NEW.reason<>'' AND encode(sha256(convert_to(NEW.reason,'UTF8')),'hex') IS DISTINCT FROM NEW.reason_sha256
       OR NEW.occurred_at > clock_timestamp() + interval '1 minute' THEN
        RAISE EXCEPTION 'suppression_record_invalid';
    END IF;
    expected := jsonb_build_object(
        'id',NEW.id::text,'ledger_id',NEW.ledger_id::text,'sequence',NEW.sequence,
        'previous_digest',NEW.previous_digest,'target_kind',NEW.target_kind,
        'target_id',NEW.target_id::text,'source_digest',NEW.source_digest,
        'case_id',NEW.case_id::text,'version',NEW.version,'previous_state',NEW.previous_state,
        'state',NEW.state,'action',NEW.action,'provider_id',NEW.provider_id,
        'subject_id',NEW.subject_id,'role',NEW.role,'auth_epoch',NEW.auth_epoch,
        'reason_sha256',NEW.reason_sha256,
        'occurred_at',to_char(NEW.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
    IF NEW.canonical_payload::jsonb IS DISTINCT FROM expected
       OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex') IS DISTINCT FROM NEW.digest THEN
        RAISE EXCEPTION 'suppression_record_seal_invalid';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER rs_event_immutable BEFORE INSERT OR UPDATE OR DELETE
  ON record_suppression_suppressionevent FOR EACH ROW EXECUTE FUNCTION rs_event_guard();
"""


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM record_suppression_suppressionevent)")
        if cursor.fetchone()[0]:
            raise RuntimeError("suppression_populated_ledger_cannot_be_removed")
        cursor.execute("DROP TRIGGER rs_event_immutable ON record_suppression_suppressionevent")
        cursor.execute("DROP FUNCTION rs_event_guard()")


class Migration(migrations.Migration):
    dependencies = [("record_suppression", "0001_initial")]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, reverse),
    ]
