# Generated for FAST9 synthetic PostgreSQL queue; production wiring is disabled.
from django.db import migrations, models
import django.db.models.deletion


FORWARD = r"""
CREATE OR REPLACE FUNCTION public.fatwa_delivery_immutable_rows() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'delivery audit rows are append-only' USING ERRCODE='23514';
END; $$;
CREATE TRIGGER fatwa_delivery_claim_immutable
BEFORE UPDATE OR DELETE ON public.fatwa_delivery_approval_claim
FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows();
CREATE TRIGGER fatwa_delivery_receipt_immutable
BEFORE UPDATE OR DELETE ON public.fatwa_delivery_provider_receipt
FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows();
CREATE TRIGGER fatwa_delivery_audit_immutable
BEFORE UPDATE OR DELETE ON public.fatwa_delivery_audit_event
FOR EACH ROW EXECUTE FUNCTION public.fatwa_delivery_immutable_rows();
"""
REVERSE = r"""
DROP TRIGGER IF EXISTS fatwa_delivery_audit_immutable ON public.fatwa_delivery_audit_event;
DROP TRIGGER IF EXISTS fatwa_delivery_receipt_immutable ON public.fatwa_delivery_provider_receipt;
DROP TRIGGER IF EXISTS fatwa_delivery_claim_immutable ON public.fatwa_delivery_approval_claim;
DROP FUNCTION IF EXISTS public.fatwa_delivery_immutable_rows();
"""


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="ApprovalClaim",
            fields=[
                ("receipt_id", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("nonce_digest", models.CharField(max_length=64, unique=True)),
                ("approval_fingerprint", models.CharField(max_length=64)),
                ("plan_fingerprint", models.CharField(max_length=64)),
                ("case_key", models.CharField(max_length=128)),
                ("answer_revision", models.PositiveIntegerField()),
                ("expected_parts", models.PositiveSmallIntegerField()),
                ("parts_manifest_sha256", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table":"fatwa_delivery_approval_claim","constraints":[
                models.CheckConstraint(condition=models.Q(("answer_revision__gte",1)),name="dq_claim_revision_positive"),
                models.CheckConstraint(condition=models.Q(("expected_parts__gte",1),("expected_parts__lte",16)),name="dq_claim_parts_bound"),
            ]},
        ),
        migrations.CreateModel(
            name="DeliveryIntent",
            fields=[
                ("intent_key", models.CharField(max_length=64,primary_key=True,serialize=False)),
                ("plan_fingerprint",models.CharField(max_length=64,unique=True)),
                ("case_key",models.CharField(max_length=128)),
                ("provider",models.CharField(max_length=64)),
                ("answer_revision",models.PositiveIntegerField()),
                ("ordinal",models.PositiveSmallIntegerField()),
                ("payload_sha256",models.CharField(max_length=64)),
                ("state",models.CharField(choices=[(x,x) for x in ("STAGED","LEASED","SENT_UNCONFIRMED","DELIVERED","FAILED_REQUIRES_REVIEW","UNKNOWN_REQUIRES_RECONCILIATION")],default="STAGED",max_length=40)),
                ("lease_token_sha256",models.CharField(blank=True,max_length=64,null=True)),
                ("lease_owner",models.CharField(blank=True,max_length=128,null=True)),
                ("lease_expires_at",models.DateTimeField(blank=True,null=True)),
                ("provider_message_id",models.CharField(blank=True,max_length=128,null=True)),
                ("provider_status",models.CharField(blank=True,max_length=16,null=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("approval",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="intents",to="delivery_queue.approvalclaim")),
            ],
            options={"db_table":"fatwa_delivery_intent","ordering":["case_key","answer_revision","ordinal"],"constraints":[
                models.UniqueConstraint(fields=("approval","ordinal"),name="dq_intent_approval_ordinal_unique"),
                models.CheckConstraint(condition=models.Q(("answer_revision__gte",1),("ordinal__gte",1),("ordinal__lte",16)),name="dq_intent_order_bound"),
                models.CheckConstraint(condition=models.Q(("payload_sha256__regex",r"^[a-f0-9]{64}$")),name="dq_intent_payload_sha_format"),
                models.CheckConstraint(condition=models.Q(("plan_fingerprint__regex",r"^[a-f0-9]{64}$")),name="dq_intent_plan_sha_format"),
                models.CheckConstraint(condition=(
                    models.Q(("state","STAGED"),("lease_token_sha256__isnull",True),("lease_owner__isnull",True),("lease_expires_at__isnull",True),("provider_message_id__isnull",True),("provider_status__isnull",True))
                    | models.Q(("state","LEASED"),("lease_token_sha256__regex",r"^[a-f0-9]{64}$"),("lease_owner__isnull",False),("lease_expires_at__isnull",False),("provider_message_id__isnull",True),("provider_status__isnull",True))
                    | models.Q(("state","SENT_UNCONFIRMED"),("lease_token_sha256__isnull",True),("lease_owner__isnull",True),("lease_expires_at__isnull",True),("provider_message_id__isnull",False),("provider_status","ACCEPTED"))
                    | models.Q(("state","DELIVERED"),("lease_token_sha256__isnull",True),("lease_owner__isnull",True),("lease_expires_at__isnull",True),("provider_message_id__isnull",False),("provider_status","DELIVERED"))
                    | models.Q(("state","FAILED_REQUIRES_REVIEW"),("lease_token_sha256__isnull",True),("lease_owner__isnull",True),("lease_expires_at__isnull",True),("provider_message_id__isnull",False),("provider_status","FAILED"))
                    | models.Q(("state","UNKNOWN_REQUIRES_RECONCILIATION"),("lease_token_sha256__regex",r"^[a-f0-9]{64}$"),("lease_owner__isnull",False),("lease_expires_at__isnull",False),("provider_message_id__isnull",True),("provider_status__isnull",True))
                ),name="dq_intent_state_consistent"),
            ]},
            indexes=[models.Index(fields=["provider","state","created_at"],name="dq_intent_claim_idx")]},
        ),
        migrations.CreateModel(
            name="ProviderReceipt",
            fields=[
                ("receipt_reference",models.CharField(max_length=128,primary_key=True,serialize=False)),
                ("provider_message_id",models.CharField(max_length=128)),
                ("reported",models.CharField(max_length=16)),
                ("payload_sha256",models.CharField(max_length=64)),
                ("recorded_at",models.DateTimeField(auto_now_add=True)),
                ("intent",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="receipts",to="delivery_queue.deliveryintent")),
            ],
            options={"db_table":"fatwa_delivery_provider_receipt","constraints":[
                models.CheckConstraint(condition=models.Q(("reported__in",["ACCEPTED","DELIVERED","FAILED"])),name="dq_receipt_reported_valid"),
                models.CheckConstraint(condition=models.Q(("payload_sha256__regex",r"^[a-f0-9]{64}$")),name="dq_receipt_payload_sha_format"),
            ]},
        ),
        migrations.CreateModel(
            name="DeliveryAuditEvent",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("old_state",models.CharField(max_length=40)),
                ("new_state",models.CharField(max_length=40)),
                ("event_reference",models.CharField(max_length=128)),
                ("event_payload_sha256",models.CharField(max_length=64)),
                ("recorded_at",models.DateTimeField(auto_now_add=True)),
                ("intent",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="audit_events",to="delivery_queue.deliveryintent")),
            ],
            options={"db_table":"fatwa_delivery_audit_event","ordering":["id"]},
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
