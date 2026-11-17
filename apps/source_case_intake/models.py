"""Append-only source receipts, review reasons and canonical evidence bindings."""

import uuid

from django.db import models


class SourceReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=16)
    account = models.CharField(max_length=128)
    event_id = models.CharField(max_length=128)
    event_key = models.CharField(max_length=64)
    message_id = models.CharField(max_length=128)
    message_key = models.CharField(max_length=64)
    conversation = models.CharField(max_length=128)
    thread = models.CharField(max_length=128, blank=True)
    sender = models.CharField(max_length=128, blank=True)
    requester_key = models.CharField(max_length=128)
    display_name = models.CharField(max_length=256, blank=True)
    parent_id = models.CharField(max_length=128, blank=True)
    original_text = models.TextField(blank=True)
    attachments = models.JSONField(default=list)
    problem = models.CharField(max_length=64, blank=True)
    raw = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event_key", "sha256"], name="sci_exact_receipt"),
        ]


class ReviewTicket(models.Model):
    receipt = models.OneToOneField(SourceReceipt, primary_key=True, on_delete=models.PROTECT)
    reason = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)


class EvidenceBinding(models.Model):
    receipt = models.OneToOneField(SourceReceipt, primary_key=True, on_delete=models.PROTECT)
    message_key = models.CharField(max_length=64, unique=True)
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    evidence = models.OneToOneField("casework.CaseEvidence", on_delete=models.PROTECT)
    action = models.CharField(max_length=16)
    subject_id = models.CharField(max_length=128, blank=True)
    provider_id = models.CharField(max_length=128, blank=True)
    auth_epoch = models.CharField(max_length=64, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AttachmentBinding(models.Model):
    receipt = models.ForeignKey(SourceReceipt, on_delete=models.PROTECT)
    source_file_id = models.CharField(max_length=128)
    attachment = models.OneToOneField("case_attachments.CaseAttachment", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "source_file_id"], name="sci_attachment_once"
            ),
        ]
