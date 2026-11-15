"""Human review gate on exact journal requests. No signing or sending."""
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
import json
import re
import unicodedata

from django.db import connection, transaction
from django.utils import timezone
from apps.delivery_queue import services as queue
from apps.delivery_queue import author_handoff as handoff
from apps.delivery_queue.approval_adapter import commit_signed_approved_plan, reserve_signed_plan
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier
from apps.editorial_export.services import require_development
from apps.fast9_case_source_join.answer_drafts import AUTHOR, CASE_KEY
from .identity import resolve_identity, require_provider
from .models import ReviewRequest, ReviewDecision

ACTIONS = frozenset({'RETURN_FOR_CHANGES', 'DECLINED', 'READY_FOR_SIGNATURE'})
HEX64 = re.compile(r'[a-f0-9]{64}')
HEX32 = re.compile(r'[a-f0-9]{32}')
MAX_REQUESTS_PER_CASE = 64


class ReviewConflict(ValueError):
    pass


def _context(case_key, synthetic_fixtures_only, author_id=AUTHOR):
    require_development(synthetic_fixtures_only)
    if case_key != CASE_KEY or type(case_key) is not str or author_id != AUTHOR:
        raise ReviewConflict('review_case_or_author_not_authorized')


def _package(directory, case_key, maximum, split):
    return handoff._build(directory, case_key=case_key, max_chars=maximum, split=split, synthetic_fixtures_only=True)


def _matches(row, package):
    if (row.case_key != package['evidence']['case_key']
        or row.answer_revision != package['evidence']['answer_revision']
        or row.plan_sha256 != package['plan_sha256']
        or row.request_sha256 != package['request_sha256'] or row.submitted_by != AUTHOR):
        raise ReviewConflict('review_request_metadata_mismatch')


def _projection(row, decision=None):
    return {'request_sha256': row.pk, 'case_key': row.case_key, 'plan_sha256': row.plan_sha256,
        'answer_revision': row.answer_revision, 'submitted_at': row.created_at.isoformat(),
        'state': decision.action if decision else 'PENDING_REVIEW',
        'note': decision.note if decision else '',
        'decided_at': decision.created_at.isoformat() if decision else None,
        'decision_id': decision.command_id if decision else None,
        'signed_approval': False}


def submit_request(directory, *, case_key, max_chars, split, author_id,
                   expected_request_sha256=None, synthetic_fixtures_only=False):
    _context(case_key, synthetic_fixtures_only, author_id)
    package, _ = _package(directory, case_key, max_chars, split)
    if expected_request_sha256 is not None and expected_request_sha256 != package['request_sha256']:
        raise ReviewConflict('author_request_is_stale')
    queue._postgres_only()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,206))', ['review-case:' + case_key])
        current, _ = _package(directory, case_key, max_chars, split)
        if current != package:
            raise ReviewConflict('request_changed_during_submission')
        row = ReviewRequest.objects.select_for_update().filter(pk=package['request_sha256']).first()
        if row is None:
            if ReviewRequest.objects.filter(case_key=case_key).count() >= MAX_REQUESTS_PER_CASE:
                raise ReviewConflict('synthetic_review_history_capacity')
            row = ReviewRequest.objects.create(request_sha256=package['request_sha256'],
                plan_sha256=package['plan_sha256'], case_key=case_key,
                answer_revision=package['evidence']['answer_revision'], submitted_by=author_id)
        _matches(row, package)
        return _projection(row, ReviewDecision.objects.filter(request=row).first())


def _note(action, note):
    if (type(action) is not str or action not in ACTIONS or type(note) is not str
        or len(note) > 1200 or (action != 'READY_FOR_SIGNATURE' and not note.strip())
        or any(unicodedata.category(c) in {'Cf', 'Cs'} or
               (unicodedata.category(c) == 'Cc' and c not in '\r\n\t') for c in note)):
        raise ReviewConflict('invalid_human_review_decision')


def record_decision(*, directory, case_key, max_chars, split, request_sha256,
                    subject_id, provider, action, note, command_id, synthetic_fixtures_only=False):
    _context(case_key, synthetic_fixtures_only)
    before = resolve_identity(provider, subject_id, case_key=case_key)
    _note(action, note)
    if (type(request_sha256) is not str or HEX64.fullmatch(request_sha256) is None
        or type(command_id) is not str or HEX32.fullmatch(command_id) is None):
        raise ReviewConflict('invalid_review_snapshot_or_command')
    package, _ = _package(directory, case_key, max_chars, split)
    if package['request_sha256'] != request_sha256:
        raise ReviewConflict('review_snapshot_is_stale')
    queue._postgres_only()
    with transaction.atomic():
        # Serialize both the request decision and an initially absent command.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,207))', [command_id])
        row = ReviewRequest.objects.select_for_update().filter(pk=request_sha256).first()
        if row is None:
            raise ReviewConflict('request_not_submitted')
        identity = resolve_identity(provider, subject_id, case_key=case_key)
        if identity.auth_epoch != before.auth_epoch:
            raise ReviewConflict('identity_changed_during_decision')
        fresh, _ = _package(directory, case_key, max_chars, split)
        _matches(row, fresh)
        payload = [request_sha256, subject_id, provider.provider_id, identity.auth_epoch, action, note, command_id]
        digest = sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        existing = ReviewDecision.objects.filter(request=row).first()
        if existing:
            if existing.command_id != command_id or not compare_digest(existing.command_sha256, digest):
                raise ReviewConflict('exact_request_already_decided')
            return _projection(row, existing)
        if ReviewDecision.objects.filter(command_id=command_id).exists():
            raise ReviewConflict('review_command_already_used')
        decision = ReviewDecision.objects.create(request=row, command_id=command_id,
            command_sha256=digest, subject_id=subject_id, provider_id=provider.provider_id,
            auth_epoch=identity.auth_epoch, action=action, note=note)
        return _projection(row, decision)


def review_history(*, case_key, author_id=AUTHOR, synthetic_fixtures_only=False):
    _context(case_key, synthetic_fixtures_only, author_id)
    queue._postgres_only()
    rows = list(ReviewRequest.objects.filter(case_key=case_key, submitted_by=author_id)
                .select_related('decision').order_by('-created_at', 'request_sha256')[:MAX_REQUESTS_PER_CASE + 1])
    if len(rows) > MAX_REQUESTS_PER_CASE:
        raise ReviewConflict('synthetic_review_history_capacity')
    return tuple(_projection(row, getattr(row, 'decision', None)) for row in rows)


def _ready_decision(package, provider, *, receipt=None):
    """Only invoked inside the existing queue transaction and after its guard."""
    row = ReviewRequest.objects.select_for_update().filter(pk=package['request_sha256']).first()
    if row is None:
        raise ReviewConflict('human_review_request_missing')
    _matches(row, package)
    decision = ReviewDecision.objects.filter(request=row).first()
    if decision is None or decision.action != 'READY_FOR_SIGNATURE':
        raise ReviewConflict('human_ready_decision_required')
    identity = resolve_identity(provider, decision.subject_id, case_key=row.case_key)
    if decision.provider_id != provider.provider_id or decision.auth_epoch != identity.auth_epoch:
        raise ReviewConflict('review_identity_epoch_changed')
    if receipt is not None:
        if receipt.approver_id != identity.subject_id:
            raise ReviewConflict('signed_approver_must_match_human_reviewer')
        try:
            issued = datetime.fromisoformat(receipt.issued_at.replace('Z', '+00:00'))
        except (ValueError, TypeError) as exc:
            raise ReviewConflict('invalid_signed_decision_time') from exc
        if not timezone.is_aware(issued) or issued < decision.created_at:
            raise ReviewConflict('signature_predates_human_review')
    return decision


def stage_reviewed_response(directory, *, case_key, max_chars, split, author_id,
                            response_json, provider, verifier, synthetic_fixtures_only=False):
    _context(case_key, synthetic_fixtures_only, author_id)
    require_provider(provider)
    if not isinstance(verifier, Ed25519ApprovalVerifier):
        raise ReviewConflict('trusted_mufti_receipt_verifier_required')
    expected, receipt = handoff.decode_signed_response(response_json)
    package, prepared = _package(directory, case_key, max_chars, split)
    if expected != package['request_sha256']:
        raise ReviewConflict('reviewed_request_is_stale')

    def current(requested_case):
        fresh, current_prepared = _package(directory, requested_case, max_chars, split)
        if fresh['request_sha256'] != expected:
            raise ReviewConflict('reviewed_source_changed_before_commit')
        _ready_decision(fresh, provider, receipt=receipt)
        return current_prepared.evidence

    rows = commit_signed_approved_plan(receipt=receipt, evidence=prepared.evidence,
        plan=prepared.plan, verify_receipt=verifier, read_current_evidence=current)
    return {'status': 'STAGED_NOT_SENT' if all(row.state == 'STAGED' for row in rows) else 'ALREADY_RECORDED',
        'request_sha256': expected, 'plan_sha256': package['plan_sha256'], 'part_count': len(rows),
        'parts': [{'ordinal': row.ordinal, 'state': row.state} for row in rows]}


def reserve_reviewed_request(directory, *, case_key, max_chars, split, request_sha256,
                             worker_id, verify_worker, provider, verifier, synthetic_fixtures_only=False):
    """Internal worker gate; still creates no network send or retry."""
    _context(case_key, synthetic_fixtures_only)
    require_provider(provider)
    package, _ = _package(directory, case_key, max_chars, split)
    if package['request_sha256'] != request_sha256:
        raise ReviewConflict('reviewed_request_is_stale')
    def current(requested_case):
        fresh, prepared = _package(directory, requested_case, max_chars, split)
        if fresh['request_sha256'] != request_sha256:
            raise ReviewConflict('reviewed_source_changed_before_reservation')
        _ready_decision(fresh, provider)
        return prepared.evidence
    return reserve_signed_plan(plan_fingerprint=package['plan_sha256'], worker_id=worker_id,
        verify_worker=verify_worker, verify_receipt=verifier, read_current_evidence=current)
