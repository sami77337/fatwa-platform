"""Frozen synthetic workflow schema. No answer/publication/account entities."""
import uuid
from functools import reduce
from operator import or_

from django.db import models
from django.db.models import F, Q, Value, Func
from django.db.models.lookups import Exact, GreaterThan, LessThanOrEqual
from django.db.models.functions import Length
from . import contracts as c


def _choices(enum):
    return [(member.value, member.value) for member in enum]


def _length_between(field, low, high, *, binary=False):
    expression = Func(F(field), function='octet_length', output_field=models.IntegerField()) if binary else Length(field)
    return GreaterThan(expression, Value(low-1)) & LessThanOrEqual(expression, Value(high))


class IntakeBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=64, default=c.SYNTHETIC_SCOPE, editable=False)
    idempotency_key = models.CharField(max_length=128)
    payload_sha256 = models.CharField(max_length=64)
    original_payload = models.BinaryField()
    payload_snapshot = models.JSONField(default=dict,editable=False)
    contract_version = models.CharField(max_length=32, default=c.CONTRACT_VERSION, editable=False)
    source_config_id = models.CharField(max_length=64, default=c.SOURCE_CONFIG_ID, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope','idempotency_key'], name='w7_batch_scope_key_unique'),
            models.CheckConstraint(condition=Q(scope=c.SYNTHETIC_SCOPE,source_config_id=c.SOURCE_CONFIG_ID,
                contract_version=c.CONTRACT_VERSION), name='w7_batch_fixed_configuration'),
            models.CheckConstraint(condition=Q(idempotency_key__regex=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'), name='w7_batch_bounded_key'),
            models.CheckConstraint(condition=Q(payload_sha256__regex=r'^[0-9a-f]{64}$'), name='w7_batch_sha256_format'),
            models.CheckConstraint(condition=_length_between('original_payload',1,c.MAX_INPUT_BYTES,binary=True), name='w7_batch_payload_bound'),
            models.CheckConstraint(condition=Exact(F('payload_sha256'),Func(
                Func(F('original_payload'),function='sha256'),Value('hex'),function='encode',output_field=models.CharField())),
                name='w7_batch_exact_payload_hash'),
        ]


class IntakeItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(IntakeBatch,on_delete=models.PROTECT,related_name='items')
    row_ordinal = models.PositiveSmallIntegerField()
    external_id = models.CharField(max_length=100,null=True,blank=True)
    question_original = models.TextField(null=True,blank=True)
    original_row = models.JSONField(null=True)
    intake_status = models.CharField(max_length=32,choices=_choices(c.IntakeStatus),default=c.IntakeStatus.RECEIVED.value)
    review_status = models.CharField(max_length=32,choices=_choices(c.ReviewStatus),default=c.ReviewStatus.UNREVIEWED.value)
    validation_results = models.JSONField(default=dict)

    class Meta:
        ordering = ['row_ordinal']
        constraints = [
            models.UniqueConstraint(fields=['batch','row_ordinal'],name='w7_item_batch_ordinal_unique'),
            models.CheckConstraint(condition=Q(row_ordinal__gte=1,row_ordinal__lte=c.MAX_ITEMS),name='w7_item_ordinal_bound'),
            models.CheckConstraint(condition=Q(intake_status__in=list(c.IntakeStatus)),name='w7_item_intake_status'),
            models.CheckConstraint(condition=Q(review_status__in=list(c.ReviewStatus)),name='w7_item_review_status'),
            models.CheckConstraint(condition=Q(external_id__isnull=True)|(
                Q(external_id__regex=r'^[^[:cntrl:]]+$')&_length_between('external_id',1,100)),name='w7_item_valid_external_id'),
        ]


class IntakeReference(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    intake_item = models.ForeignKey(IntakeItem,on_delete=models.PROTECT,related_name='references')
    reference_ordinal = models.PositiveSmallIntegerField()
    original_pointer = models.JSONField(null=True)
    reference_status = models.CharField(max_length=16,choices=_choices(c.ReferenceStatus),default=c.ReferenceStatus.UNVERIFIED.value)
    verification_results = models.JSONField(default=dict)
    verified_identity = models.JSONField(default=dict)
    citation_text = models.TextField(blank=True,default='')

    class Meta:
        ordering = ['reference_ordinal']
        constraints = [
            models.UniqueConstraint(fields=['intake_item','reference_ordinal'],name='w7_ref_item_ordinal_unique'),
            models.CheckConstraint(condition=Q(reference_ordinal__gte=1,reference_ordinal__lte=c.MAX_REFERENCES_PER_ITEM),name='w7_ref_ordinal_bound'),
            models.CheckConstraint(condition=Q(reference_status__in=list(c.ReferenceStatus)),name='w7_ref_status'),
            models.CheckConstraint(condition=(Q(reference_status='VERIFIED') & reduce(or_, [
                Q(verified_identity=dict(value)) & (
                    Q(original_pointer={'source_id':'W7-SOURCE','heading_id':f'W7-HEADING-{value["source_row_id"]}'}) |
                    Q(original_pointer={key:item for key,item in value.items() if key not in ('edition_id','source_row_id')}))
                for value in c.VERIFIED_IDENTITIES]) |
                (Q(reference_status__in=['UNVERIFIED','MISMATCHED'],verified_identity={},citation_text=''))),
                name='w7_ref_verified_identity_only'),
        ]


class ReviewEvent(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    intake_item = models.ForeignKey(IntakeItem,on_delete=models.PROTECT,related_name='review_events')
    operation_id = models.UUIDField()
    action = models.CharField(max_length=32,choices=_choices(c.ReviewAction))
    from_status = models.CharField(max_length=32,choices=_choices(c.ReviewStatus))
    to_status = models.CharField(max_length=32,choices=_choices(c.ReviewStatus))
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at','id']
        constraints = [
            models.UniqueConstraint(fields=['intake_item','operation_id'],name='w7_event_item_operation_unique'),
            models.CheckConstraint(condition=reduce(or_,[
                Q(from_status=source,action=action,to_status=target)
                for (source,action),target in c.REVIEW_TRANSITIONS.items()]),name='w7_event_allowed_transition'),
            models.CheckConstraint(condition=Q(reason__regex=r'\S')&_length_between('reason',1,c.MAX_REASON_CHARS),name='w7_event_reason_bound'),
        ]
