"""Database guards also apply to bulk_create and direct SQL writes."""
from django.db import migrations

FORWARD = """
CREATE FUNCTION reference_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Source catalog snapshots are immutable' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER reference_work_immutable BEFORE UPDATE OR DELETE
ON reference_referencework FOR EACH ROW EXECUTE FUNCTION reference_reject_mutation();
CREATE TRIGGER reference_edition_immutable BEFORE UPDATE OR DELETE
ON reference_referenceedition FOR EACH ROW EXECUTE FUNCTION reference_reject_mutation();
CREATE TRIGGER reference_heading_immutable BEFORE UPDATE OR DELETE
ON reference_referenceheading FOR EACH ROW EXECUTE FUNCTION reference_reject_mutation();
CREATE FUNCTION reference_check_parent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_edition bigint;
    parent_depth smallint;
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        SELECT edition_id, depth INTO parent_edition, parent_depth
        FROM reference_referenceheading WHERE id = NEW.parent_id;
        IF NOT FOUND OR parent_edition <> NEW.edition_id OR parent_depth + 1 <> NEW.depth THEN
            RAISE EXCEPTION 'Parent must exist in the same edition at the preceding depth'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER reference_heading_parent BEFORE INSERT
ON reference_referenceheading FOR EACH ROW EXECUTE FUNCTION reference_check_parent();
"""

REVERSE = """
DROP TRIGGER reference_heading_parent ON reference_referenceheading;
DROP FUNCTION reference_check_parent();
DROP TRIGGER reference_heading_immutable ON reference_referenceheading;
DROP TRIGGER reference_edition_immutable ON reference_referenceedition;
DROP TRIGGER reference_work_immutable ON reference_referencework;
DROP FUNCTION reference_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("reference", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
