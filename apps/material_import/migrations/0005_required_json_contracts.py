"""Missing JSON keys must fail closed, not become an SQL UNKNOWN condition."""

from importlib import import_module

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION mi_plan_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b record; m record; c record; expected integer;
BEGIN
 SELECT * INTO b FROM material_import_importbatch WHERE id=NEW.batch_id FOR UPDATE;
 SELECT * INTO m FROM material_import_mappingrevision WHERE id=NEW.mapping_id;
 SELECT revision,evidence_version INTO c FROM casework_case WHERE id=b.case_id;
 SELECT coalesce(max(number),0)+1 INTO expected FROM material_import_importplan WHERE batch_id=NEW.batch_id;
 IF jsonb_typeof(NEW.report) IS DISTINCT FROM 'object'
 OR jsonb_typeof(NEW.report->'rows') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.report->'ready') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(NEW.report->'unreferenced_files') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.report->'counts') IS DISTINCT FROM 'object'
 OR NEW.report->>'schema' IS DISTINCT FROM 'fatwa.material-import.v1'
 THEN RAISE EXCEPTION 'invalid material import plan shape' USING ERRCODE='23514'; END IF;
 IF m.batch_id IS DISTINCT FROM NEW.batch_id
 OR m.number<>(SELECT max(number) FROM material_import_mappingrevision WHERE batch_id=NEW.batch_id)
 OR NEW.number<>expected OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version
 OR NEW.expires_at<>b.expires_at OR NEW.expires_at<=clock_timestamp()
 OR jsonb_array_length(NEW.report->'rows') NOT BETWEEN 1 AND 20
 OR octet_length(NEW.report::text)>524288
 OR NEW.digest!~'^[a-f0-9]{64}$' OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.report->'rows') r WHERE
 jsonb_typeof(r) IS DISTINCT FROM 'object'
 OR jsonb_typeof(r->'action') IS DISTINCT FROM 'string'
 OR jsonb_typeof(r->'external_id') IS DISTINCT FROM 'string'
 OR jsonb_typeof(r->'group') IS DISTINCT FROM 'string'
 OR r->>'action' NOT IN ('ADD','SKIP','UPDATE','BLOCK'))
 OR ((NEW.report->>'ready')::boolean AND (
 EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.report->'rows') r WHERE r->>'action'='BLOCK')
 OR jsonb_array_length(NEW.report->'unreferenced_files')<>0
 OR (SELECT count(*) FROM jsonb_array_elements(NEW.report->'rows'))<>(SELECT count(DISTINCT r->>'external_id') FROM jsonb_array_elements(NEW.report->'rows') r)))
 THEN RAISE EXCEPTION 'invalid material import plan' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION mi_roundtrip_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM id FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF jsonb_typeof(NEW.scope) IS DISTINCT FROM 'object'
 OR jsonb_typeof(NEW.scope->'selected') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.scope->'prepared_at') IS DISTINCT FROM 'string'
 OR jsonb_typeof(NEW.manifest) IS DISTINCT FROM 'object'
 OR NEW.manifest->>'schema' IS DISTINCT FROM 'fatwa.material-import.v1'
 OR NEW.manifest->'synthetic' IS DISTINCT FROM 'true'::jsonb
 OR NEW.manifest->>'records' IS DISTINCT FROM 'records.json'
 OR jsonb_typeof(NEW.manifest->'files') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.manifest->'origin') IS DISTINCT FROM 'object'
 OR NEW.manifest->'origin'->>'schema' IS DISTINCT FROM 'fatwa.material-roundtrip.v1'
 OR jsonb_typeof(NEW.manifest->'origin'->'namespace') IS DISTINCT FROM 'string'
 OR jsonb_typeof(NEW.manifest->'origin'->'mapping') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.manifest->'origin'->'prepared_at') IS DISTINCT FROM 'string'
 OR NEW.manifest->'origin'->>'prepared_at' IS DISTINCT FROM NEW.scope->>'prepared_at'
 THEN RAISE EXCEPTION 'invalid material transfer receipt shape' USING ERRCODE='23514'; END IF;
 IF NEW.scope_digest!~'^[a-f0-9]{64}$' OR NEW.artifact_sha256!~'^[a-f0-9]{64}$'
 OR jsonb_array_length(NEW.scope->'selected') NOT BETWEEN 1 AND 20
 OR jsonb_array_length(NEW.manifest->'origin'->'mapping')<>jsonb_array_length(NEW.scope->'selected')
 OR jsonb_array_length(NEW.manifest->'files')>20
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR (SELECT count(*) FROM material_import_roundtripreceipt WHERE case_id=NEW.case_id)>=32
 THEN RAISE EXCEPTION 'invalid material transfer receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

# Reversal restores precisely the previous function definitions and keeps rows.
prior_plan = import_module("apps.material_import.migrations.0002_integrity").SQL
prior_transfer = import_module("apps.material_import.migrations.0004_roundtrip_guards").SQL
REVERSE = (
    prior_plan[
        prior_plan.index("CREATE FUNCTION mi_plan_insert()") : prior_plan.index(
            "CREATE FUNCTION mi_decision_insert()"
        )
    ]
    + prior_transfer[: prior_transfer.index("CREATE TRIGGER")]
).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


class Migration(migrations.Migration):
    dependencies = [("material_import", "0004_roundtrip_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
