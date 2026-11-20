from django.db import migrations

SQL = r"""
CREATE FUNCTION organization_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'organization history immutable' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NOT FOUND OR NEW.version <> COALESCE((SELECT max(version) FROM case_organization_organizationrevision WHERE case_id=NEW.case_id),0)+1
    OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
    OR jsonb_typeof(NEW.tags)<>'array' OR jsonb_typeof(NEW.question_types)<>'array'
    OR jsonb_array_length(NEW.tags)>16 OR jsonb_array_length(NEW.question_types)>17
    OR length(NEW.note)>2000 THEN
  RAISE EXCEPTION 'organization snapshot invalid' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.tags) t WHERE jsonb_typeof(t)<>'string' OR length(t#>>'{}') NOT BETWEEN 1 AND 48 OR (t#>>'{}')!~'\S')
    OR (SELECT count(*) FROM jsonb_array_elements(NEW.tags))<>(SELECT count(DISTINCT t) FROM jsonb_array_elements(NEW.tags) t)
    OR (SELECT count(*) FROM jsonb_array_elements(NEW.question_types))<>(SELECT count(DISTINCT t) FROM jsonb_array_elements(NEW.question_types) t)
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.question_types) t WHERE jsonb_typeof(t)<>'string' OR (t#>>'{}') NOT IN (
      'RULING','VALIDITY','SUFFICIENCY','MAKEUP','EXPIATION','COMPENSATION','RIGHTS','EFFECT','METHOD','CALCULATION','TIME','CONDITIONS','ELIGIBILITY','DISTRIBUTION','DISPUTE','CORRECTION','EDUCATION')) THEN
  RAISE EXCEPTION 'organization values invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER organization_revision_guard BEFORE INSERT OR UPDATE OR DELETE
ON case_organization_organizationrevision FOR EACH ROW EXECUTE FUNCTION organization_revision_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("case_organization", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER organization_revision_guard ON case_organization_organizationrevision;
        DROP FUNCTION organization_revision_guard();
    """,
        )
    ]
