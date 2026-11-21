"""Append-only human identity observations and membership corrections."""

import uuid

from django.db import models
from django.db.models import Q


class Sealed(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_id = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class PlatformIdentity(Sealed):
    source = models.CharField(max_length=24)
    account = models.CharField(max_length=128)
    source_subject = models.CharField(max_length=128)
    identity_key = models.CharField(max_length=64, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source", "account", "source_subject"), name="ir_platform_key"
            ),
            models.CheckConstraint(
                condition=Q(source__in=("telegram", "youtube", "website", "WEBSITE_SESSION")),
                name="ir_source_kind",
            ),
        ]


class IdentityObservation(Sealed):
    identity = models.ForeignKey(PlatformIdentity, on_delete=models.PROTECT)
    case = models.OneToOneField("casework.Case", on_delete=models.PROTECT)
    receipt_id = models.UUIDField(null=True)
    origin_digest = models.CharField(max_length=64)
    display_name = models.CharField(max_length=256, blank=True)
    request_key = models.UUIDField(unique=True)


class Person(Sealed):
    """An internal optional human grouping, not a civil-name or login assertion."""

    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    label = models.CharField(max_length=256)
    reason = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)


class LinkProposal(Sealed):
    identity = models.ForeignKey(PlatformIdentity, on_delete=models.PROTECT)
    person = models.ForeignKey(Person, on_delete=models.PROTECT)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    previous_digest = models.CharField(max_length=64)
    evidence = models.CharField(max_length=2000)
    request_key = models.UUIDField(unique=True)


class RegistryOperation(Sealed):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    kind = models.CharField(max_length=12)
    proposal = models.OneToOneField(LinkProposal, null=True, on_delete=models.PROTECT)
    source_person = models.ForeignKey(
        Person, null=True, related_name="outgoing_operations", on_delete=models.PROTECT
    )
    target_person = models.ForeignKey(
        Person, null=True, related_name="incoming_operations", on_delete=models.PROTECT
    )
    changes = models.JSONField()
    reason = models.CharField(max_length=2000)
    preview_digest = models.CharField(max_length=64)
    request_key = models.UUIDField(unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("VERIFY", "REJECT", "UNLINK", "MERGE", "SPLIT")),
                name="ir_operation_kind",
            )
        ]


class IdentityMembership(Sealed):
    identity = models.ForeignKey(PlatformIdentity, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    person = models.ForeignKey(Person, null=True, on_delete=models.PROTECT)
    operation = models.ForeignKey(RegistryOperation, on_delete=models.PROTECT)
    previous_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("identity", "sequence"), name="ir_member_sequence"),
            models.UniqueConstraint(fields=("identity", "operation"), name="ir_member_operation"),
            models.CheckConstraint(
                condition=Q(sequence__gte=1, sequence__lte=2048), name="ir_member_bound"
            ),
        ]
