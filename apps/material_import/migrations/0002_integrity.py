from django.db import migrations

SQL = r"""
CREATE FUNCTION mi_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'material import history is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION mi_batch_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c record;
BEGIN
 SELECT revision,evidence_version INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT FOUND OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version
 OR octet_length(NEW.raw) NOT BETWEEN 1 AND 192000
 OR encode(sha256(NEW.raw),'hex')<>NEW.raw_sha256
 OR length(NEW.provenance) NOT BETWEEN 1 AND 1000 OR btrim(NEW.provenance)=''
 OR length(NEW.rights_basis) NOT BETWEEN 1 AND 1000 OR btrim(NEW.rights_basis)=''
 OR NEW.expires_at<=NEW.created_at OR NEW.expires_at>NEW.created_at+interval '1 hour'
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR (SELECT count(*) FROM material_import_importbatch WHERE case_id=NEW.case_id)>=32 THEN
 RAISE EXCEPTION 'invalid material import source receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION mi_mapping_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer;
BEGIN
 PERFORM id FROM material_import_importbatch WHERE id=NEW.batch_id FOR UPDATE;
 SELECT coalesce(max(number),0)+1 INTO expected FROM material_import_mappingrevision WHERE batch_id=NEW.batch_id;
 IF NEW.number<>expected OR jsonb_typeof(NEW.mapping)<>'object'
 OR (SELECT count(*) FROM jsonb_object_keys(NEW.mapping))<>15
 OR NOT (NEW.mapping ?& ARRAY['external_id','kind','title','work_title','edition_label','creator','description',
 'source_locator','provenance','rights_basis','language','source_version','recorded_text','file_member','group'])
 OR EXISTS(SELECT 1 FROM jsonb_each(NEW.mapping) x WHERE jsonb_typeof(x.value)<>'string' OR length(x.value#>>'{}')>100)
 OR jsonb_typeof(NEW.resolutions)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(NEW.resolutions))>20
 OR NEW.digest!~'^[a-f0-9]{64}$' OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR EXISTS(SELECT 1 FROM material_import_groupresult g JOIN material_import_importplan p ON p.id=g.plan_id WHERE p.batch_id=NEW.batch_id)
 THEN RAISE EXCEPTION 'invalid material import mapping' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION mi_plan_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b record; m record; c record; expected integer;
BEGIN
 SELECT * INTO b FROM material_import_importbatch WHERE id=NEW.batch_id FOR UPDATE;
 SELECT * INTO m FROM material_import_mappingrevision WHERE id=NEW.mapping_id;
 SELECT revision,evidence_version INTO c FROM casework_case WHERE id=b.case_id;
 SELECT coalesce(max(number),0)+1 INTO expected FROM material_import_importplan WHERE batch_id=NEW.batch_id;
 IF m.batch_id IS DISTINCT FROM NEW.batch_id
 OR m.number<>(SELECT max(number) FROM material_import_mappingrevision WHERE batch_id=NEW.batch_id)
 OR NEW.number<>expected OR NEW.case_revision<>c.revision OR NEW.evidence_version<>c.evidence_version
 OR NEW.expires_at<>b.expires_at OR NEW.expires_at<=clock_timestamp()
 OR jsonb_typeof(NEW.report)<>'object' OR jsonb_typeof(NEW.report->'rows')<>'array'
 OR jsonb_array_length(NEW.report->'rows') NOT BETWEEN 1 AND 20
 OR jsonb_typeof(NEW.report->'ready')<>'boolean' OR octet_length(NEW.report::text)>524288
 OR NEW.report->>'schema'<>'fatwa.material-import.v1'
 OR NEW.digest!~'^[a-f0-9]{64}$' OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.report->'rows') r WHERE r->>'action' NOT IN ('ADD','SKIP','UPDATE','BLOCK'))
 OR ((NEW.report->>'ready')::boolean AND (
 EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.report->'rows') r WHERE r->>'action'='BLOCK')
 OR jsonb_array_length(NEW.report->'unreferenced_files')<>0
 OR (SELECT count(*) FROM jsonb_array_elements(NEW.report->'rows'))<>(SELECT count(DISTINCT r->>'external_id') FROM jsonb_array_elements(NEW.report->'rows') r)))
 THEN RAISE EXCEPTION 'invalid material import plan' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION mi_decision_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record; b record; m record;
BEGIN
 SELECT * INTO p FROM material_import_importplan WHERE id=NEW.plan_id;
 SELECT * INTO b FROM material_import_importbatch WHERE id=p.batch_id FOR UPDATE;
 SELECT * INTO m FROM material_import_mappingrevision WHERE id=p.mapping_id;
 IF p.id IS NULL OR p.number<>(SELECT max(number) FROM material_import_importplan WHERE batch_id=b.id)
 OR m.number<>(SELECT max(number) FROM material_import_mappingrevision WHERE batch_id=b.id)
 OR p.expires_at<=clock_timestamp() OR b.expires_at<=clock_timestamp()
 OR (NEW.provider_id=ANY(ARRAY[p.provider_id,b.provider_id,m.provider_id]) AND
 ((NEW.provider_id=p.provider_id AND NEW.subject_id=p.subject_id)
 OR (NEW.provider_id=b.provider_id AND NEW.subject_id=b.subject_id)
 OR (NEW.provider_id=m.provider_id AND NEW.subject_id=m.subject_id)))
 OR (NEW.verdict='APPROVE' AND NOT (p.report->>'ready')::boolean)
 OR length(NEW.note) NOT BETWEEN 1 AND 2000 OR btrim(NEW.note)=''
 OR length(NEW.verification_note) NOT BETWEEN 1 AND 2000 OR btrim(NEW.verification_note)=''
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 THEN RAISE EXCEPTION 'invalid independent import decision' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION mi_group_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record; b record; wanted integer;
BEGIN
 SELECT * INTO p FROM material_import_importplan WHERE id=NEW.plan_id;
 SELECT * INTO b FROM material_import_importbatch WHERE id=p.batch_id FOR UPDATE;
 SELECT count(*) INTO wanted FROM jsonb_array_elements(p.report->'rows') r WHERE r->>'group'=NEW.group_key;
 IF p.id IS NULL OR p.expires_at<=clock_timestamp() OR b.expires_at<=clock_timestamp()
 OR NOT EXISTS(SELECT 1 FROM material_import_importdecision WHERE plan_id=NEW.plan_id AND verdict='APPROVE')
 OR EXISTS(SELECT 1 FROM material_import_importevent WHERE batch_id=b.id AND action='CANCEL')
 OR p.number<>(SELECT max(number) FROM material_import_importplan WHERE batch_id=b.id)
 OR jsonb_typeof(NEW.outcomes)<>'array' OR wanted NOT BETWEEN 1 AND 20 OR jsonb_array_length(NEW.outcomes)<>wanted
 OR NEW.digest!~'^[a-f0-9]{64}$' OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.outcomes) o WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_array_elements(p.report->'rows') r WHERE r->>'group'=NEW.group_key
 AND r->>'external_id'=o->>'external_id' AND r->>'action'=o->>'action' AND r->>'action'<>'BLOCK'))
 OR (SELECT count(DISTINCT o->>'external_id') FROM jsonb_array_elements(NEW.outcomes) o)<>wanted
 THEN RAISE EXCEPTION 'invalid canonical import group receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION mi_event_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous record; expected integer;
BEGIN
 PERFORM id FROM material_import_importbatch WHERE id=NEW.batch_id FOR UPDATE;
 SELECT * INTO previous FROM material_import_importevent WHERE batch_id=NEW.batch_id ORDER BY sequence DESC LIMIT 1;
 expected:=coalesce(previous.sequence,0)+1;
 IF NEW.sequence<>expected OR NEW.previous_digest<>coalesce(previous.digest,repeat('0',64))
 OR (expected=1 AND NEW.action<>'STAGE') OR (expected>1 AND NEW.action='STAGE')
 OR NEW.digest!~'^[a-f0-9]{64}$' OR jsonb_typeof(NEW.detail)<>'object' OR octet_length(NEW.detail::text)>16000
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR EXISTS(SELECT 1 FROM material_import_importevent WHERE batch_id=NEW.batch_id AND action='CANCEL')
 THEN RAISE EXCEPTION 'invalid material import journal' USING ERRCODE='23514'; END IF;
 IF NEW.action='APPLY' AND NOT EXISTS(SELECT 1 FROM material_import_groupresult g
 JOIN material_import_importplan p ON p.id=g.plan_id WHERE p.batch_id=NEW.batch_id
 AND p.id::text=NEW.detail->>'plan' AND g.group_key=NEW.detail->>'group')
 THEN RAISE EXCEPTION 'import event lacks canonical receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

TABLES = {
    "importbatch": "mi_batch_insert",
    "mappingrevision": "mi_mapping_insert",
    "importplan": "mi_plan_insert",
    "importdecision": "mi_decision_insert",
    "groupresult": "mi_group_insert",
    "importevent": "mi_event_insert",
}

for table, function in TABLES.items():
    SQL += f"CREATE TRIGGER mi_{table}_immutable BEFORE UPDATE OR DELETE ON material_import_{table} FOR EACH ROW EXECUTE FUNCTION mi_immutable();\n"
    SQL += f"CREATE TRIGGER mi_{table}_insert BEFORE INSERT ON material_import_{table} FOR EACH ROW EXECUTE FUNCTION {function}();\n"

REVERSE = ""
for table, function in TABLES.items():
    REVERSE += f"DROP TRIGGER mi_{table}_insert ON material_import_{table}; DROP TRIGGER mi_{table}_immutable ON material_import_{table}; DROP FUNCTION {function}();\n"
REVERSE += "DROP FUNCTION mi_immutable();"


class Migration(migrations.Migration):
    dependencies = [("material_import", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
