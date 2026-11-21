"""Append-only derivatives; canonical answers and recording bytes stay original."""

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class ImmutableRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    case_revision = models.PositiveIntegerField()
    evidence_version = models.PositiveIntegerField()
    request_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    canonical_payload = models.TextField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True


class RecordingTranscript(ImmutableRecord):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    part = models.ForeignKey("answer_media.AnswerPart", on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField()
    previous = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    source_pins = models.JSONField()
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    segments = models.JSONField(default=list)
    change_kind = models.CharField(max_length=20)
    note = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["part", "number"], name="pam_transcript_number"),
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "request_key"], name="pam_transcript_request"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="pam_transcript_number_bound"
            ),
            models.CheckConstraint(
                condition=Q(change_kind__in=("EDITORIAL", "MEANING_REVIEW")),
                name="pam_transcript_change_kind",
            ),
        ]


class TranscriptAction(ImmutableRecord):
    transcript = models.ForeignKey(
        RecordingTranscript, on_delete=models.PROTECT, related_name="actions"
    )
    sequence = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    action = models.CharField(max_length=20)
    note = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "sequence"], name="pam_transcript_action_seq"
            ),
            models.UniqueConstraint(
                fields=["transcript", "action"], name="pam_transcript_action_once"
            ),
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "request_key"],
                name="pam_transcript_action_req",
            ),
            models.CheckConstraint(
                condition=Q(action__in=("REVIEW", "APPROVE_MEANING", "WITHDRAW")),
                name="pam_transcript_action_kind",
            ),
        ]


class PublicMediaEdition(ImmutableRecord):
    case = models.ForeignKey("casework.Case", on_delete=models.PROTECT)
    publication = models.ForeignKey(
        "experimental_publication.PublicationEdition", on_delete=models.PROTECT
    )
    part = models.ForeignKey("answer_media.AnswerPart", on_delete=models.PROTECT)
    transcript = models.ForeignKey(RecordingTranscript, on_delete=models.PROTECT, null=True)
    number = models.PositiveSmallIntegerField()
    previous = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    label = models.CharField(max_length=120)
    note = models.TextField()
    source_pins = models.JSONField()
    publication_sha256 = models.CharField(max_length=64)
    transcript_digest = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["publication", "part", "number"], name="pam_media_number"
            ),
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "request_key"], name="pam_media_request"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=64), name="pam_media_number_bound"
            ),
        ]


class PublicMediaAction(ImmutableRecord):
    edition = models.ForeignKey(
        PublicMediaEdition, on_delete=models.PROTECT, related_name="actions"
    )
    sequence = models.PositiveSmallIntegerField()
    previous_digest = models.CharField(max_length=64)
    action = models.CharField(max_length=16)
    note = models.TextField()
    valid_until = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["edition", "sequence"], name="pam_media_action_seq"),
            models.UniqueConstraint(fields=["edition", "action"], name="pam_media_action_once"),
            models.UniqueConstraint(
                fields=["provider_id", "subject_id", "request_key"], name="pam_media_action_request"
            ),
            models.CheckConstraint(
                condition=Q(action__in=("REVIEW", "RELEASE", "WITHDRAW")),
                name="pam_media_action_kind",
            ),
            models.CheckConstraint(
                condition=Q(action="RELEASE", valid_until__isnull=False)
                | (~Q(action="RELEASE") & Q(valid_until__isnull=True)),
                name="pam_media_action_lease",
            ),
        ]
