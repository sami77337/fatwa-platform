from django.db import migrations

SQL = r"""
CREATE FUNCTION mi_roundtrip_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM id FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NEW.scope_digest!~'^[a-f0-9]{64}$' OR NEW.artifact_sha256!~'^[a-f0-9]{64}$'
 OR jsonb_typeof(NEW.scope)<>'object' OR jsonb_typeof(NEW.scope->'selected')<>'array'
 OR jsonb_array_length(NEW.scope->'selected') NOT BETWEEN 1 AND 20
 OR jsonb_typeof(NEW.manifest)<>'object' OR NEW.manifest->>'schema'<>'fatwa.material-import.v1'
 OR NEW.manifest->'origin'->>'schema'<>'fatwa.material-roundtrip.v1'
 OR NEW.manifest->'origin'->>'prepared_at'<>NEW.scope->>'prepared_at'
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR (SELECT count(*) FROM material_import_roundtripreceipt WHERE case_id=NEW.case_id)>=32
 THEN RAISE EXCEPTION 'invalid material transfer receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER mi_roundtripreceipt_insert BEFORE INSERT ON material_import_roundtripreceipt
FOR EACH ROW EXECUTE FUNCTION mi_roundtrip_insert();
CREATE TRIGGER mi_roundtripreceipt_immutable BEFORE UPDATE OR DELETE ON material_import_roundtripreceipt
FOR EACH ROW EXECUTE FUNCTION mi_immutable();
"""
REVERSE = """
DROP TRIGGER mi_roundtripreceipt_insert ON material_import_roundtripreceipt;
DROP TRIGGER mi_roundtripreceipt_immutable ON material_import_roundtripreceipt;
DROP FUNCTION mi_roundtrip_insert();
"""


class Migration(migrations.Migration):
    dependencies = [("material_import", "0003_roundtripreceipt")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
