"""Add isolated append-only review rows; never convert an existing decision."""
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

FORWARD = """
CREATE FUNCTION public.fatwa_mufti_review_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'Mufti review rows are append-only' USING ERRCODE='23514';
END; $$;
CREATE TRIGGER mr_request_immutable BEFORE UPDATE OR DELETE ON public.fatwa_mufti_review_request
FOR EACH ROW EXECUTE FUNCTION public.fatwa_mufti_review_immutable();
CREATE TRIGGER mr_decision_immutable BEFORE UPDATE OR DELETE ON public.fatwa_mufti_review_decision
FOR EACH ROW EXECUTE FUNCTION public.fatwa_mufti_review_immutable();
"""
REVERSE = """
DROP TRIGGER mr_decision_immutable ON public.fatwa_mufti_review_decision;
DROP TRIGGER mr_request_immutable ON public.fatwa_mufti_review_request;
DROP FUNCTION public.fatwa_mufti_review_immutable();
"""


class Migration(migrations.Migration):
    initial = True
    dependencies = [('delivery_queue', '0004_required_state_fields')]
    operations = [
        migrations.CreateModel(name='ReviewRequest', fields=[
            ('request_sha256', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('plan_sha256', models.CharField(max_length=64)),
            ('case_key', models.CharField(max_length=128)),
            ('answer_revision', models.PositiveIntegerField()),
            ('submitted_by', models.CharField(max_length=128)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
        ], options={'db_table': 'fatwa_mufti_review_request', 'ordering': ['-created_at', 'request_sha256'],
            'indexes': [models.Index(fields=['case_key', 'created_at'], name='mr_case_created_idx')],
            'constraints': [
                models.CheckConstraint(condition=models.Q(request_sha256__regex=r'^[a-f0-9]{64}$'), name='mr_request_hash_valid'),
                models.CheckConstraint(condition=models.Q(plan_sha256__regex=r'^[a-f0-9]{64}$'), name='mr_plan_hash_valid'),
                models.CheckConstraint(condition=models.Q(answer_revision__gte=1), name='mr_answer_revision_positive'),
            ]}),
        migrations.CreateModel(name='ReviewDecision', fields=[
            ('request', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True,
                related_name='decision', serialize=False, to='mufti_review.reviewrequest')),
            ('command_id', models.CharField(max_length=32, unique=True)),
            ('command_sha256', models.CharField(max_length=64)),
            ('subject_id', models.CharField(max_length=128)),
            ('provider_id', models.CharField(max_length=128)),
            ('auth_epoch', models.CharField(max_length=64)),
            ('action', models.CharField(max_length=32)),
            ('note', models.CharField(max_length=1200)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
        ], options={'db_table': 'fatwa_mufti_review_decision', 'constraints': [
            models.CheckConstraint(condition=models.Q(action__in=['RETURN_FOR_CHANGES', 'DECLINED', 'READY_FOR_SIGNATURE']), name='mr_decision_action_valid'),
            models.CheckConstraint(condition=models.Q(command_id__regex=r'^[a-f0-9]{32}$'), name='mr_command_id_valid'),
            models.CheckConstraint(condition=models.Q(command_sha256__regex=r'^[a-f0-9]{64}$'), name='mr_command_hash_valid'),
        ]}),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
