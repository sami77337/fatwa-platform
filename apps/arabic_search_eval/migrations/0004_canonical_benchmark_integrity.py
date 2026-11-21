from importlib import import_module

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION ase_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb; expected_id jsonb; document record; generation record; pin jsonb;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'evaluation version immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NEW.number<>(SELECT count(*)+1 FROM arabic_search_eval_evaluationrevision WHERE case_id=NEW.case_id AND engine=NEW.engine)
 OR NEW.corpus_sha256 !~ '^[a-f0-9]{64}$' OR NEW.judgements_sha256 !~ '^[a-f0-9]{64}$'
 OR jsonb_typeof(NEW.corpus)<>'object' OR NEW.corpus->>'synthetic_only' IS DISTINCT FROM 'true'
 OR jsonb_typeof(NEW.judgements)<>'array' OR jsonb_array_length(NEW.judgements) NOT BETWEEN 1 AND 64
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.ranker_version='' OR NEW.note !~ '\S'
 THEN RAISE EXCEPTION 'evaluation version invalid' USING ERRCODE='23514'; END IF;
 IF NEW.engine='CANONICAL_FTS' THEN
   IF (NEW.corpus-ARRAY['synthetic_only','source_pin','records'])<>'{}'::jsonb
   OR NOT(NEW.corpus ?& ARRAY['synthetic_only','source_pin','records'])
   OR jsonb_typeof(NEW.corpus->'records') IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.corpus->'records') NOT BETWEEN 1 AND 64
   OR jsonb_array_length(NEW.judgements)>8
   OR octet_length(NEW.corpus::text)+octet_length(NEW.judgements::text)>262144
   OR NEW.ranker_version !~ '^canonical-fts-benchmark-v1:[a-f0-9]{64}$'
   OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(NEW.corpus->'records'))<>jsonb_array_length(NEW.corpus->'records')
   OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(NEW.judgements))<>jsonb_array_length(NEW.judgements)
   OR (SELECT count(DISTINCT value->>'query') FROM jsonb_array_elements(NEW.judgements))<>jsonb_array_length(NEW.judgements)
   THEN RAISE EXCEPTION 'invalid canonical benchmark corpus' USING ERRCODE='23514'; END IF;
   pin:=NEW.corpus->'source_pin';
   SELECT * INTO generation FROM canonical_search_searchgeneration WHERE case_id=NEW.case_id ORDER BY number DESC LIMIT 1;
   IF generation.id IS NULL OR jsonb_typeof(pin) IS DISTINCT FROM 'object'
   OR NOT(pin ?& ARRAY['case_id','generation_id','generation_digest','source_fingerprint','allowed_fingerprint'])
   OR (pin-ARRAY['case_id','generation_id','generation_digest','source_fingerprint','allowed_fingerprint'])<>'{}'::jsonb
   OR pin->>'case_id' IS DISTINCT FROM NEW.case_id::text
   OR pin->>'generation_id' IS DISTINCT FROM generation.id::text
   OR pin->>'generation_digest' IS DISTINCT FROM generation.digest
   OR pin->>'source_fingerprint' IS DISTINCT FROM generation.source_fingerprint
   OR (pin->>'allowed_fingerprint' ~ '^[a-f0-9]{64}$') IS NOT TRUE
   THEN RAISE EXCEPTION 'canonical benchmark needs current generation' USING ERRCODE='23514'; END IF;
   FOR item IN SELECT value FROM jsonb_array_elements(NEW.corpus->'records') LOOP
     SELECT * INTO document FROM canonical_search_searchdocument WHERE generation_id=generation.id AND id::text=item->>'id';
     IF document.id IS NULL OR jsonb_typeof(item) IS DISTINCT FROM 'object'
     OR NOT(item ?& ARRAY['id','digest','kind','pin']) OR (item-ARRAY['id','digest','kind','pin'])<>'{}'::jsonb
     OR item->>'digest' IS DISTINCT FROM document.digest OR item->>'kind' IS DISTINCT FROM document.kind
     OR item->'pin' IS DISTINCT FROM document.pin
     THEN RAISE EXCEPTION 'canonical corpus document changed' USING ERRCODE='23514'; END IF;
   END LOOP;
   FOR item IN SELECT value FROM jsonb_array_elements(NEW.judgements) LOOP
     IF jsonb_typeof(item) IS DISTINCT FROM 'object'
     OR NOT(item ?& ARRAY['id','query','expected','rationale'])
     OR (item-ARRAY['id','query','expected','rationale'])<>'{}'::jsonb
     OR (item->>'id' ~ '^[a-z][a-z0-9._-]{0,39}$') IS NOT TRUE
     OR jsonb_typeof(item->'query') IS DISTINCT FROM 'string' OR length(btrim(item->>'query')) NOT BETWEEN 1 AND 120
     OR jsonb_typeof(item->'rationale') IS DISTINCT FROM 'string' OR length(btrim(item->>'rationale')) NOT BETWEEN 1 AND 1000
     OR jsonb_typeof(item->'expected') IS DISTINCT FROM 'array' OR jsonb_array_length(item->'expected')>64
     OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(item->'expected'))<>jsonb_array_length(item->'expected')
     THEN RAISE EXCEPTION 'canonical benchmark judgment invalid' USING ERRCODE='23514'; END IF;
     FOR expected_id IN SELECT value FROM jsonb_array_elements(item->'expected') LOOP
       IF jsonb_typeof(expected_id) IS DISTINCT FROM 'string'
       OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.corpus->'records') r WHERE r->'id'=expected_id)
       THEN RAISE EXCEPTION 'canonical expected document outside corpus' USING ERRCODE='23514'; END IF;
     END LOOP;
   END LOOP;
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.judgements) q WHERE jsonb_array_length(q->'expected')>0)
   THEN RAISE EXCEPTION 'positive canonical judgment required' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION ase_decision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r arabic_search_eval_evaluationrevision%ROWTYPE; item jsonb;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'evaluation decision immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM arabic_search_eval_evaluationrevision WHERE id=NEW.revision_id;
 PERFORM 1 FROM casework_case WHERE id=r.case_id FOR UPDATE;
 IF r.number<>(SELECT max(number) FROM arabic_search_eval_evaluationrevision WHERE case_id=r.case_id AND engine=r.engine)
 OR (r.provider_id=NEW.provider_id AND r.subject_id=NEW.subject_id)
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.note !~ '\S'
 OR jsonb_typeof(NEW.reviews)<>'array' OR jsonb_array_length(NEW.reviews)<>jsonb_array_length(r.judgements)
 THEN RAISE EXCEPTION 'current independent evaluation review required' USING ERRCODE='23514'; END IF;
 IF r.engine='CANONICAL_FTS' THEN
   IF (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(NEW.reviews))<>jsonb_array_length(NEW.reviews)
   THEN RAISE EXCEPTION 'duplicate canonical judgment review' USING ERRCODE='23514'; END IF;
   FOR item IN SELECT value FROM jsonb_array_elements(NEW.reviews) LOOP
     IF jsonb_typeof(item) IS DISTINCT FROM 'object'
     OR NOT(item ?& ARRAY['id','verdict','note']) OR (item-ARRAY['id','verdict','note'])<>'{}'::jsonb
     OR coalesce(item->>'verdict','') NOT IN ('AGREE','DISAGREE')
     OR (NEW.action='APPROVE' AND item->>'verdict'<>'AGREE')
     OR jsonb_typeof(item->'note') IS DISTINCT FROM 'string' OR length(btrim(item->>'note')) NOT BETWEEN 1 AND 1000
     OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.judgements) q WHERE q->'id'=item->'id')
     THEN RAISE EXCEPTION 'complete canonical judgment review required' USING ERRCODE='23514'; END IF;
   END LOOP;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION ase_canonical_benchmark_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c record; suite record; judged record; dictionary record; approval record; run record;
        generation record; observed record; item jsonb; q jsonb; metric jsonb; idx integer;
BEGIN
 SELECT * INTO c FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF c.id IS NULL OR c.revision<>NEW.case_revision OR c.evidence_version<>NEW.evidence_version
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch=''
 OR NEW.canonical_payload::jsonb IS DISTINCT FROM to_jsonb(NEW)-ARRAY['canonical_payload','digest','created_at']
 OR octet_length(NEW.canonical_payload)>1048576
 OR encode(sha256(convert_to(NEW.canonical_payload,'UTF8')),'hex')<>NEW.digest
 OR length(btrim(NEW.note)) NOT BETWEEN 1 AND 1000
 THEN RAISE EXCEPTION 'invalid canonical benchmark identity or payload' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='arabic_search_eval_canonicalbenchmarkrun' THEN
   SELECT * INTO suite FROM arabic_search_eval_evaluationrevision WHERE id=NEW.revision_id;
   SELECT * INTO judged FROM arabic_search_eval_evaluationdecision WHERE id=NEW.judgement_decision_id;
   SELECT * INTO dictionary FROM canonical_search_synonymrevision WHERE id=NEW.dictionary_id;
   SELECT * INTO approval FROM canonical_search_synonymdecision WHERE revision_id=NEW.dictionary_id ORDER BY sequence DESC LIMIT 1;
   IF suite.id IS NULL OR suite.engine<>'CANONICAL_FTS' OR suite.case_id<>NEW.case_id
   OR suite.number<>(SELECT max(number) FROM arabic_search_eval_evaluationrevision WHERE case_id=NEW.case_id AND engine='CANONICAL_FTS')
   OR judged.id IS NULL OR judged.revision_id<>suite.id OR judged.action<>'APPROVE'
   OR dictionary.id IS NULL OR dictionary.case_id<>NEW.case_id
   OR approval.id IS DISTINCT FROM NEW.dictionary_approval_id OR approval.action IS DISTINCT FROM 'APPROVE'
   OR approval.valid_until<=clock_timestamp()
   OR NEW.source_pin IS DISTINCT FROM suite.corpus->'source_pin'
   OR (SELECT count(*) FROM arabic_search_eval_canonicalbenchmarkrun WHERE case_id=NEW.case_id)>=64
   OR jsonb_typeof(NEW.comparisons) IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.comparisons)<>jsonb_array_length(suite.judgements)
   OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(NEW.comparisons))<>jsonb_array_length(NEW.comparisons)
   OR jsonb_typeof(NEW.metrics) IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.metrics->'queries') IS DISTINCT FROM 'array'
   OR jsonb_array_length(NEW.metrics->'queries')<>jsonb_array_length(suite.judgements)
   OR NEW.metrics->'synthetic_only' IS DISTINCT FROM 'true'::jsonb
   OR NEW.metrics->>'precision_denominator' IS DISTINCT FROM 'returned_top_5_count'
   OR jsonb_typeof(NEW.regressions) IS DISTINCT FROM 'array'
   OR NEW.regression_status<>(CASE WHEN jsonb_array_length(NEW.regressions)>0 THEN 'HOLD' ELSE 'CLEAR' END)
   THEN RAISE EXCEPTION 'current reviewed canonical benchmark inputs required' USING ERRCODE='23514'; END IF;
   SELECT * INTO generation FROM canonical_search_searchgeneration WHERE case_id=NEW.case_id ORDER BY number DESC LIMIT 1;
   IF generation.id::text IS DISTINCT FROM NEW.source_pin->>'generation_id'
   OR generation.digest IS DISTINCT FROM NEW.source_pin->>'generation_digest'
   OR jsonb_typeof(NEW.code_pin) IS DISTINCT FROM 'object'
   OR NEW.code_pin->>'version' IS DISTINCT FROM 'canonical-fts-benchmark-v1'
   OR NEW.code_pin->>'baseline_profile' IS DISTINCT FROM 'ar-simple-trigram-dev-v1'
   OR NEW.code_pin->>'scorer' IS DISTINCT FROM 'arabic_search_eval.evaluation.score:k=5'
   OR NEW.code_pin->>'precision_denominator' IS DISTINCT FROM 'returned_top_5_count'
   OR NEW.code_pin->'ranking_window' IS DISTINCT FROM '5'::jsonb
   OR NEW.code_pin->'observation_window' IS DISTINCT FROM '20'::jsonb
   OR NEW.code_pin->>'regression_rule' IS DISTINCT FROM 'per_query_quality_negative_errors_and_5x_or_50ms_total_latency_v1'
   OR jsonb_typeof(NEW.code_pin->'files') IS DISTINCT FROM 'object'
   OR NOT((NEW.code_pin->'files') ?& ARRAY['canonical_search/text.py','canonical_search/services.py','canonical_search/governance.py','arabic_search_eval/evaluation.py','arabic_search_eval/benchmark.py'])
   OR ((NEW.code_pin->'files')-ARRAY['canonical_search/text.py','canonical_search/services.py','canonical_search/governance.py','arabic_search_eval/evaluation.py','arabic_search_eval/benchmark.py'])<>'{}'::jsonb
   OR EXISTS(SELECT 1 FROM jsonb_each_text(NEW.code_pin->'files') f WHERE f.value !~ '^[a-f0-9]{64}$')
   OR jsonb_typeof(NEW.workload) IS DISTINCT FROM 'object'
   OR NEW.workload->'query_pairs' IS DISTINCT FROM to_jsonb(jsonb_array_length(suite.judgements))
   OR NEW.workload->'external_ai_calls' IS DISTINCT FROM '0'::jsonb
   OR NEW.workload->'monetary_cost' IS DISTINCT FROM 'null'::jsonb
   OR NEW.workload->>'cost_status' IS DISTINCT FROM 'LOCAL_DATABASE_CURRENCY_COST_NOT_MEASURED'
   OR NEW.workload->>'count_scope' IS DISTINCT FROM 'shadow_execution_and_source_checks_only'
   OR (NEW.workload->>'sql_statements' ~ '^[0-9]+$') IS NOT TRUE
   OR (NEW.workload->>'sql_selects' ~ '^[0-9]+$') IS NOT TRUE
   OR (NEW.workload->>'sql_selects')::integer NOT BETWEEN 1 AND (NEW.workload->>'sql_statements')::integer
   THEN RAISE EXCEPTION 'canonical benchmark source code or workload invalid' USING ERRCODE='23514'; END IF;
   idx:=0;
   FOR item IN SELECT value FROM jsonb_array_elements(NEW.comparisons) LOOP
     q:=suite.judgements->idx; metric:=NEW.metrics->'queries'->idx;
     SELECT * INTO observed FROM canonical_search_shadowcomparison WHERE id::text=item->>'id';
     IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR (item-ARRAY['id','digest'])<>'{}'::jsonb
     OR observed.id IS NULL OR observed.digest IS DISTINCT FROM item->>'digest'
     OR observed.case_id<>NEW.case_id OR observed.revision_id<>dictionary.id OR observed.approval_id<>approval.id
     OR observed.source_pin IS DISTINCT FROM NEW.source_pin OR observed.query IS DISTINCT FROM q->>'query'
     OR metric->>'id' IS DISTINCT FROM q->>'id' OR metric->>'query' IS DISTINCT FROM q->>'query'
     OR metric->'expected' IS DISTINCT FROM q->'expected'
     OR metric->>'comparison_id' IS DISTINCT FROM observed.id::text OR metric->>'comparison_digest' IS DISTINCT FROM observed.digest
     OR metric->>'candidate_status' IS DISTINCT FROM observed.candidate_status
     OR metric->'baseline_ms' IS DISTINCT FROM to_jsonb(observed.baseline_ms)
     OR metric->'candidate_ms' IS DISTINCT FROM to_jsonb(observed.candidate_ms)
     OR metric->'baseline' IS DISTINCT FROM coalesce((SELECT jsonb_agg(r->'document_id' ORDER BY n) FROM jsonb_array_elements(observed.baseline->'rows') WITH ORDINALITY AS rows(r,n)),'[]'::jsonb)
     OR metric->'candidate' IS DISTINCT FROM coalesce((SELECT jsonb_agg(r->'document_id' ORDER BY n) FROM jsonb_array_elements(observed.candidate->'rows') WITH ORDINALITY AS rows(r,n)),'[]'::jsonb)
     THEN RAISE EXCEPTION 'canonical metric does not reference exact actual comparison' USING ERRCODE='23514'; END IF;
     idx:=idx+1;
   END LOOP;
 ELSE
   SELECT * INTO run FROM arabic_search_eval_canonicalbenchmarkrun WHERE id=NEW.run_id;
   SELECT * INTO suite FROM arabic_search_eval_evaluationrevision WHERE id=run.revision_id;
   SELECT * INTO approval FROM canonical_search_synonymdecision WHERE revision_id=run.dictionary_id ORDER BY sequence DESC LIMIT 1;
   SELECT * INTO generation FROM canonical_search_searchgeneration WHERE case_id=NEW.case_id ORDER BY number DESC LIMIT 1;
   IF run.id IS NULL OR run.case_id<>NEW.case_id
   OR (run.provider_id=NEW.provider_id AND run.subject_id=NEW.subject_id)
   OR (suite.provider_id=NEW.provider_id AND suite.subject_id=NEW.subject_id)
   OR suite.number<>(SELECT max(number) FROM arabic_search_eval_evaluationrevision WHERE case_id=NEW.case_id AND engine='CANONICAL_FTS')
   OR approval.id IS DISTINCT FROM run.dictionary_approval_id OR approval.action IS DISTINCT FROM 'APPROVE' OR approval.valid_until<=clock_timestamp()
   OR generation.id::text IS DISTINCT FROM run.source_pin->>'generation_id'
   OR (NEW.action='ACCEPT' AND run.regression_status<>'CLEAR')
   THEN RAISE EXCEPTION 'independent current run review without regressions required' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ase_canonical_run_insert BEFORE INSERT ON arabic_search_eval_canonicalbenchmarkrun
 FOR EACH ROW EXECUTE FUNCTION ase_canonical_benchmark_insert();
CREATE TRIGGER ase_canonical_run_immutable BEFORE UPDATE OR DELETE ON arabic_search_eval_canonicalbenchmarkrun
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
CREATE TRIGGER ase_canonical_review_insert BEFORE INSERT ON arabic_search_eval_canonicalbenchmarkdecision
 FOR EACH ROW EXECUTE FUNCTION ase_canonical_benchmark_insert();
CREATE TRIGGER ase_canonical_review_immutable BEFORE UPDATE OR DELETE ON arabic_search_eval_canonicalbenchmarkdecision
 FOR EACH ROW EXECUTE FUNCTION cs_immutable();
"""

# Rollback restores the exact title-word guards that predate the engine column.
OLD = import_module("apps.arabic_search_eval.migrations.0002_immutable_review").SQL
REVISION = OLD.split("CREATE FUNCTION ase_revision_guard()", 1)[1].split("CREATE TRIGGER", 1)[0]
DECISION = OLD.split("CREATE FUNCTION ase_decision_guard()", 1)[1].split("CREATE TRIGGER", 1)[0]
REVERSE = (
    """
DROP TRIGGER ase_canonical_review_immutable ON arabic_search_eval_canonicalbenchmarkdecision;
DROP TRIGGER ase_canonical_review_insert ON arabic_search_eval_canonicalbenchmarkdecision;
DROP TRIGGER ase_canonical_run_immutable ON arabic_search_eval_canonicalbenchmarkrun;
DROP TRIGGER ase_canonical_run_insert ON arabic_search_eval_canonicalbenchmarkrun;
DROP FUNCTION ase_canonical_benchmark_insert();
"""
    + "CREATE OR REPLACE FUNCTION ase_revision_guard()"
    + REVISION
    + "CREATE OR REPLACE FUNCTION ase_decision_guard()"
    + DECISION
)


class Migration(migrations.Migration):
    dependencies = [
        ("arabic_search_eval", "0003_canonicalbenchmarkdecision_canonicalbenchmarkrun_and_more")
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
