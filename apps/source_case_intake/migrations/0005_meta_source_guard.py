"""Extend the immutable source insert whitelist for signed Meta fixtures.

Only the known synthetic provider source names change. Raw SHA-256, bounded
length, JSON structure, account namespace, immutability and evidence-parent
constraints remain byte-for-byte identical to migration 0002. Existing rows
and original bytes are never touched.
"""

from django.db import migrations


def _receipt_guard(sources):
    quoted = ",".join("'" + item + "'" for item in sources)
    return f"""
CREATE OR REPLACE FUNCTION sci_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF octet_length(NEW.raw) NOT BETWEEN 1 AND 262144
    OR encode(sha256(NEW.raw), 'hex') <> NEW.sha256
    OR NEW.source NOT IN ({quoted})
    OR NEW.account NOT LIKE 'synthetic-%'
    OR jsonb_typeof(NEW.attachments) <> 'array' THEN
  RAISE EXCEPTION 'invalid source receipt' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""


OLD = ("telegram", "youtube", "website")
EXTENDED = (*OLD, "facebook", "messenger", "instagram", "whatsapp")

# Rollback must not silently strand newer receipts behind an older source
# whitelist: refuse until the owner resolves their dependent Meta history.
REVERSE = """
DO $$
BEGIN
 IF EXISTS (
  SELECT 1 FROM source_case_intake_sourcereceipt
  WHERE source NOT IN ('telegram','youtube','website')
 ) THEN
  RAISE EXCEPTION 'meta receipt history requires explicit rollback decision'
    USING ERRCODE='23514';
 END IF;
END $$;
""" + _receipt_guard(OLD)


class Migration(migrations.Migration):
    dependencies = [("source_case_intake", "0004_review_note_guards")]

    operations = [migrations.RunSQL(_receipt_guard(EXTENDED), reverse_sql=REVERSE)]
