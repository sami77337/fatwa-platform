"""Validate exact item provenance once per batch in each INSERT statement."""
from django.db import migrations


FORWARD = r"""
CREATE FUNCTION public.wave7_check_inserted_original_rows() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_batch record; item record; raw bytea; array_span integer[];
        starts integer[]; ends integer[]; token json; token_bytes bytea;
        next_at integer; row_json json; question text;
BEGIN
    -- The transition relation contains only this statement's actual inserts.
    -- No persistent/session cache, caller-supplied index or relaxed write permit.
    FOR source_batch IN SELECT DISTINCT batch_id FROM wave7_inserted_items LOOP
        SELECT original_payload INTO raw FROM public.intake_workflow_intakebatch
            WHERE id=source_batch.batch_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Wave7 source batch absent' USING ERRCODE='23514';
        END IF;
        array_span:=public.wave7_json_member_span(raw,'items');
        IF array_span IS NULL THEN
            RAISE EXCEPTION 'Wave7 exact original row span mismatch' USING ERRCODE='23514';
        END IF;
        starts:=ARRAY[]::integer[];
        ends:=ARRAY[]::integer[];
        next_at:=array_span[1]+1;
        -- json (never jsonb/numeric) preserves token spelling. Parse the array
        -- once, then advance through delimiters and exact token byte lengths.
        -- Avoid copying/searching the entire remaining array for every token.
        FOR token IN SELECT value FROM json_array_elements(convert_from(
            substring(raw FROM array_span[1]+1 FOR array_span[2]-array_span[1]),'UTF8')::json) LOOP
            WHILE next_at<array_span[2] AND get_byte(raw,next_at) IN (9,10,13,32,44) LOOP
                next_at:=next_at+1;
            END LOOP;
            token_bytes:=convert_to(token::text,'UTF8');
            IF substring(raw FROM next_at+1 FOR octet_length(token_bytes)) IS DISTINCT FROM token_bytes THEN
                RAISE EXCEPTION 'Wave7 element source unavailable' USING ERRCODE='23514';
            END IF;
            starts:=array_append(starts,next_at);
            next_at:=next_at+octet_length(token_bytes);
            ends:=array_append(ends,next_at);
        END LOOP;
        FOR item IN SELECT * FROM wave7_inserted_items WHERE batch_id=source_batch.batch_id LOOP
            IF item.row_ordinal NOT BETWEEN 1 AND cardinality(starts)
               OR ROW(item.source_byte_start,item.source_byte_end) IS DISTINCT FROM
                  ROW(starts[item.row_ordinal],ends[item.row_ordinal])
               OR convert_to(item.original_row,'UTF8') IS DISTINCT FROM substring(raw
                  FROM starts[item.row_ordinal]+1 FOR ends[item.row_ordinal]-starts[item.row_ordinal]) THEN
                RAISE EXCEPTION 'Wave7 exact original row span mismatch' USING ERRCODE='23514';
            END IF;
            row_json:=item.original_row::json;
            question:=NULL;
            IF json_typeof(row_json->'question')='string' THEN question:=row_json->>'question'; END IF;
            IF item.question_original IS DISTINCT FROM question THEN
                RAISE EXCEPTION 'Wave7 original question mismatch' USING ERRCODE='23514';
            END IF;
            IF item.external_id IS NOT NULL AND (json_typeof(row_json->'external_id') IS DISTINCT FROM 'string'
                OR item.external_id IS DISTINCT FROM row_json->>'external_id') THEN
                RAISE EXCEPTION 'Wave7 original external ID mismatch' USING ERRCODE='23514';
            END IF;
        END LOOP;
    END LOOP;
    RETURN NULL;
END; $$;

DROP TRIGGER w7_20_source_snapshot ON public.intake_workflow_intakeitem;
CREATE TRIGGER w7_20_source_snapshot AFTER INSERT ON public.intake_workflow_intakeitem
    REFERENCING NEW TABLE AS wave7_inserted_items
    FOR EACH STATEMENT EXECUTE FUNCTION public.wave7_check_inserted_original_rows();
"""

REVERSE = r"""
DROP TRIGGER w7_20_source_snapshot ON public.intake_workflow_intakeitem;
CREATE TRIGGER w7_20_source_snapshot BEFORE INSERT ON public.intake_workflow_intakeitem
    FOR EACH ROW EXECUTE FUNCTION public.wave7_check_original_row();
DROP FUNCTION public.wave7_check_inserted_original_rows();
"""


class Migration(migrations.Migration):
    dependencies = [('intake_workflow', '0004_lossless_numeric_storage')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
