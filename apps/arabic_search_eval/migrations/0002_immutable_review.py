from django.db import migrations

SQL = r"""
CREATE FUNCTION ase_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'evaluation version immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM casework_case WHERE id=NEW.case_id FOR UPDATE;
 IF NEW.number<>(SELECT count(*)+1 FROM arabic_search_eval_evaluationrevision WHERE case_id=NEW.case_id)
 OR NEW.corpus_sha256 !~ '^[a-f0-9]{64}$' OR NEW.judgements_sha256 !~ '^[a-f0-9]{64}$'
 OR jsonb_typeof(NEW.corpus)<>'object' OR NEW.corpus->>'synthetic_only' IS DISTINCT FROM 'true'
 OR jsonb_typeof(NEW.judgements)<>'array' OR jsonb_array_length(NEW.judgements) NOT BETWEEN 1 AND 64
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.ranker_version='' OR NEW.note !~ '\S' THEN
  RAISE EXCEPTION 'evaluation version invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ase_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON arabic_search_eval_evaluationrevision
 FOR EACH ROW EXECUTE FUNCTION ase_revision_guard();
CREATE FUNCTION ase_decision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r arabic_search_eval_evaluationrevision%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'evaluation decision immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM arabic_search_eval_evaluationrevision WHERE id=NEW.revision_id;
 PERFORM 1 FROM casework_case WHERE id=r.case_id FOR UPDATE;
 IF r.number<>(SELECT max(number) FROM arabic_search_eval_evaluationrevision WHERE case_id=r.case_id)
 OR (r.provider_id=NEW.provider_id AND r.subject_id=NEW.subject_id)
 OR NEW.subject_id='' OR NEW.provider_id='' OR NEW.auth_epoch='' OR NEW.note !~ '\S'
 OR jsonb_typeof(NEW.reviews)<>'array' OR jsonb_array_length(NEW.reviews)<>jsonb_array_length(r.judgements) THEN
  RAISE EXCEPTION 'current independent evaluation review required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ase_decision_guard BEFORE INSERT OR UPDATE OR DELETE ON arabic_search_eval_evaluationdecision
 FOR EACH ROW EXECUTE FUNCTION ase_decision_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("arabic_search_eval", "0001_initial")]
    operations = [
        migrations.RunSQL(
            SQL,
            """
        DROP TRIGGER ase_decision_guard ON arabic_search_eval_evaluationdecision;
        DROP FUNCTION ase_decision_guard();
        DROP TRIGGER ase_revision_guard ON arabic_search_eval_evaluationrevision;
        DROP FUNCTION ase_revision_guard();
    """,
        )
    ]
