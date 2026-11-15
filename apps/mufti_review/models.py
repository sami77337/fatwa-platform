"""Append-only review metadata; no approval signature, answer body or token."""
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ReviewRequest(models.Model):
    request_sha256 = models.CharField(max_length=64, primary_key=True)
    plan_sha256 = models.CharField(max_length=64)
    case_key = models.CharField(max_length=128)
    answer_revision = models.PositiveIntegerField()
    submitted_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'fatwa_mufti_review_request'
        ordering = ['-created_at', 'request_sha256']
        indexes = [models.Index(fields=['case_key', 'created_at'], name='mr_case_created_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(request_sha256__regex=r'^[a-f0-9]{64}$'), name='mr_request_hash_valid'),
            models.CheckConstraint(condition=Q(plan_sha256__regex=r'^[a-f0-9]{64}$'), name='mr_plan_hash_valid'),
            models.CheckConstraint(condition=Q(answer_revision__gte=1), name='mr_answer_revision_positive'),
        ]


class ReviewDecision(models.Model):
    request = models.OneToOneField(ReviewRequest, primary_key=True, on_delete=models.PROTECT, related_name='decision')
    command_id = models.CharField(max_length=32, unique=True)
    command_sha256 = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    provider_id = models.CharField(max_length=128)
    auth_epoch = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    note = models.CharField(max_length=1200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'fatwa_mufti_review_decision'
        constraints = [
            models.CheckConstraint(condition=Q(action__in=['RETURN_FOR_CHANGES', 'DECLINED', 'READY_FOR_SIGNATURE']), name='mr_decision_action_valid'),
            models.CheckConstraint(condition=Q(command_id__regex=r'^[a-f0-9]{32}$'), name='mr_command_id_valid'),
            models.CheckConstraint(condition=Q(command_sha256__regex=r'^[a-f0-9]{64}$'), name='mr_command_hash_valid'),
        ]
