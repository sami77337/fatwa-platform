from django.db import migrations

SQL = r"""
CREATE FUNCTION cs_unique_sources() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(DISTINCT entry->'pin') FROM jsonb_array_elements(NEW.manifest) entry)
    <>jsonb_array_length(NEW.manifest)
 THEN RAISE EXCEPTION 'search generation contains duplicate source pins' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cs_generation_unique_sources BEFORE INSERT ON canonical_search_searchgeneration
 FOR EACH ROW EXECUTE FUNCTION cs_unique_sources();
"""


class Migration(migrations.Migration):
    dependencies = [("canonical_search", "0002_integrity")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER cs_generation_unique_sources ON canonical_search_searchgeneration; DROP FUNCTION cs_unique_sources();",
        )
    ]
