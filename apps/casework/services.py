"""One operational source of truth for multiple isolated synthetic cases.

This module neither sends messages nor treats approval as delivery. The legacy
tracking row provides a capability binding only; its stage is never authoritative.
"""

import json
import re
import secrets
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from hashlib import sha256

from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.delivery_queue import services as queue
from apps.delivery_queue.models import (
    RequesterTrackingCase,
    RequesterTrackingEvent,
    RequesterTrackingToken,
)
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity
from apps.platform_recovery.integration import mutation_service

from .models import AnswerRevision, Case, CaseDecision, CaseEvent, CaseEvidence, CaseSource

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_TOKEN = re.compile(r"rt_[A-Za-z0-9_-]{43}")
MAX_HISTORY = 256
MAX_TEXT = 16000


class CaseConflict(ValueError):
    """Safe fixed denial codes without user text or secret identifiers."""


def _digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def _answer_manifest(answer):
    """Validate an optional multipart revision under the caller's case lock."""
    if answer is None:
        return None
    if not django_apps.is_installed("apps.answer_media"):
        raise CaseConflict("answer_media_schema_unavailable")
    from apps.answer_media.services import manifest_for_locked_answer

    return manifest_for_locked_answer(answer)


def _answer_citations(answer):
    """Recheck current citation rights under the caller's canonical case lock.

    Citation-free compositions keep their existing behavior. Actual citations
    retain source integrity checks and, when enabled, require current CITE rights.
    This never substitutes for identity, current facts or human approval.
    """
    if answer is None:
        return []
    if not django_apps.is_installed("apps.case_citations"):
        # A restored database may still contain citations even when its app was
        # omitted from a composition. Enforcement cannot infer their absence.
        if getattr(settings, "FATWA_SOURCE_RIGHTS_ENFORCED", False) is not False:
            raise CaseConflict("citation_schema_unavailable")
        return []
    from apps.case_citations.services import citations_for_locked_answer

    return citations_for_locked_answer(answer)


_TIMED_USE_DEADLINES = ContextVar("casework_timed_use_deadlines", default=())


def _answer_timed(answer, *, actor=None, provider=None):
    """Validate persisted timed annotations; an editing flag never erases them.

    Before approval the caller supplies its authorized actor. Downstream use
    re-resolves the actual scholarly approver, not a requester/anonymous viewer
    impersonation. Timed READ_MEDIA/CITE cannot authorize publication or release.
    Return the conservative expiry for final collection-wide checks.
    """
    if answer is None:
        return None
    table = "timed_citations_timedcitation"
    if not django_apps.is_installed("apps.timed_citations"):
        # An omitted app cannot hide restored annotations. Legacy schemas and
        # genuinely annotation-free answers retain their prior behavior.
        if table in connection.introspection.table_names():
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT 1 FROM "{table}" WHERE answer_id = %s LIMIT 1', [answer.pk])
                if cursor.fetchone():
                    raise CaseConflict("timed_citation_schema_unavailable")
        return None
    from apps.timed_citations.models import TimedCitation

    if not TimedCitation.objects.filter(answer=answer).exists():
        return None
    if actor is None:
        decision = getattr(answer, "decision", None)
        provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if (decision is None or decision.action != "APPROVE" or provider is None
                or getattr(provider, "provider_id", None) != decision.provider_id):
            raise CaseConflict("timed_approval_authority_unavailable")
        actor = _identity(provider, decision.subject_id, answer.case)
        if actor.auth_epoch != decision.auth_epoch:
            raise CaseConflict("timed_approval_authority_changed")
    if provider is None:
        raise CaseConflict("timed_approval_authority_unavailable")
    from apps.source_rights.services import projection_expiry_guard
    from apps.timed_citations.services import for_locked_answer

    # Collect the already-validated bounds inside the existing projection guard.
    # A fresh policy callback after the hook's final identity check could revoke
    # that identity while returning its former deadline, exposing private bytes.
    with projection_expiry_guard() as deadlines:
        for_locked_answer(answer=answer, actor=actor, provider=provider)
        earliest = min(deadlines, default=None)
    for scope in _TIMED_USE_DEADLINES.get():
        if earliest is not None:
            scope[0] = earliest if scope[0] is None else min(scope[0], earliest)
    return earliest


@contextmanager
def _answer_use_boundary():
    # Only timed uses contribute here. Existing book collections keep their
    # own filtered-result expiry semantics; no annotation means no new denial.
    # One earliest bound per nesting scope, never a cached permission or media.
    earliest = [None]
    token = _TIMED_USE_DEADLINES.set((*_TIMED_USE_DEADLINES.get(), earliest))
    try:
        yield
        if earliest[0] is not None and earliest[0] <= timezone.now():
            raise CaseConflict("timed_grant_expired")
    finally:
        _TIMED_USE_DEADLINES.reset(token)


def _delivery_origin_for_locked_case(case):
    """Read durable inbound origin even when its intake UI is disabled.

    Legacy CaseSource uses WEBSITE for the reused intake mechanism. Source-backed
    cases must resolve their immutable receipt; they may never silently downgrade
    to website channel capabilities when a composition is missing that schema.
    """
    source = case.source
    if not source.source_event_id.startswith("source:"):
        values = [str(case.pk), case.requester_id, source.channel, source.source_event_id]
        return {"channel": source.channel, "identity_sha256": _digest(json.dumps(values))}
    if not django_apps.is_installed("apps.source_case_intake"):
        raise CaseConflict("source_origin_schema_unavailable")
    from apps.source_case_intake.models import EvidenceBinding

    binding = (
        EvidenceBinding.objects.select_related("receipt", "evidence")
        .filter(case=case, evidence__version=1, action="CREATED")
        .first()
    )
    if binding is None:
        raise CaseConflict("source_origin_unavailable")
    row = binding.receipt
    if (
        source.source_event_id != "source:" + str(row.pk)
        or row.requester_key != case.requester_id
        or row.original_text != binding.evidence.text
        or row.original_text != source.original_question
        or row.sha256 != sha256(bytes(row.raw)).hexdigest()
        or row.source not in {"website", "telegram", "youtube"}
    ):
        raise CaseConflict("source_origin_inconsistent")
    values = [
        str(row.pk),
        row.sha256,
        row.source,
        row.account,
        row.conversation,
        row.thread,
        row.sender,
        row.message_id,
        str(case.pk),
    ]
    return {"channel": row.source, "identity_sha256": _digest(json.dumps(values))}


def _guard(ack):
    if ack is not True:
        raise CaseConflict("synthetic_ack_required")
    try:
        queue._postgres_only()
    except queue.QueueConflict as exc:
        raise CaseConflict("case_backend_unavailable") from exc


def _ref(value):
    return type(value) is str and _REF.fullmatch(value) is not None


def _text(value, *, optional=False):
    if (
        type(value) is not str
        or len(value) > MAX_TEXT
        or "\x00" in value
        or (not optional and not value.strip())
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise CaseConflict("invalid_case_text")


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CaseConflict("case_access_denied") from exc


def _identity(provider, subject_id, case):
    try:
        return resolve_identity(provider, subject_id, case_key=case.public_ref)
    except IdentityUnavailable as exc:
        raise CaseConflict("case_access_denied") from exc


def _case(case_id, *, lock=False):
    query = Case.objects.select_for_update() if lock else Case.objects
    row = query.filter(pk=_uuid(case_id)).first()
    if row is None:
        raise CaseConflict("case_access_denied")
    return row


def _mutation_versions(expected_revision, expected_evidence_version):
    if (
        type(expected_revision) is not int
        or expected_revision < 1
        or type(expected_evidence_version) is not int
        or expected_evidence_version < 1
    ):
        raise CaseConflict("invalid_expected_versions")


def _versions(case, expected_revision, expected_evidence_version=None):
    if type(expected_revision) is not int or expected_revision != case.revision:
        raise CaseConflict("case_revision_changed")
    if expected_evidence_version is not None and (
        type(expected_evidence_version) is not int
        or expected_evidence_version != case.evidence_version
    ):
        raise CaseConflict("case_evidence_changed")
    if case.revision >= MAX_HISTORY:
        raise CaseConflict("case_history_capacity")


def _verify(case):
    """Validate immutable history against all mutable operational pointers."""
    if case.tracking_id != "case:" + str(case.pk):
        raise CaseConflict("case_tracking_mismatch")
    source = CaseSource.objects.filter(case=case).first()
    if source is None or _digest(source.original_question) != source.question_sha256:
        raise CaseConflict("case_source_inconsistent")
    evidence = list(case.evidence.order_by("version")[: MAX_HISTORY + 1])
    if len(evidence) != case.evidence_version or not 1 <= len(evidence) <= MAX_HISTORY:
        raise CaseConflict("case_evidence_inconsistent")
    for number, item in enumerate(evidence, 1):
        if (
            item.version != number
            or _digest(item.text) != item.text_sha256
            or (number == 1 and (item.kind != "ORIGINAL" or item.text != source.original_question))
            or (number > 1 and item.kind != "FOLLOWUP")
        ):
            raise CaseConflict("case_evidence_inconsistent")
    answers = list(case.answers.order_by("revision")[: MAX_HISTORY + 1])
    if len(answers) != case.answer_revision or len(answers) > MAX_HISTORY:
        raise CaseConflict("case_answer_inconsistent")
    by_answer = {}
    for number, answer in enumerate(answers, 1):
        if (
            answer.revision != number
            or _digest(answer.text) != answer.text_sha256
            or not 1 <= answer.evidence_version <= case.evidence_version
        ):
            raise CaseConflict("case_answer_inconsistent")
        by_answer[answer.pk] = answer
    events = list(case.events.select_related("decision").order_by("sequence")[: MAX_HISTORY + 1])
    if len(events) != case.revision or not 1 <= len(events) <= MAX_HISTORY:
        raise CaseConflict("case_history_inconsistent")
    decision_ids = set(case.decisions.values_list("id", flat=True))
    event_decisions = {event.decision_id for event in events if event.decision_id is not None}
    if decision_ids != event_decisions:
        raise CaseConflict("case_decision_history_inconsistent")
    stage, ev, ar, approved = "RECEIVED", 1, 0, None
    for number, event in enumerate(events, 1):
        if event.sequence != number or (number == 1) != (event.action == "INTAKE"):
            raise CaseConflict("case_history_inconsistent")
        if event.action == "FOLLOWUP":
            ev += 1
            stage, approved = "UNDER_REVIEW", None
        elif event.action == "SAVE_ANSWER":
            ar += 1
            stage, approved = "UNDER_REVIEW", None
            answer = by_answer.get(event.answer_id)
            if answer is None or (answer.revision, answer.evidence_version) != (ar, ev):
                raise CaseConflict("case_history_inconsistent")
        elif event.action == "CLARIFICATION":
            stage, approved = "NEEDS_CLARIFICATION", None
        elif event.action in ("APPROVE", "RETURN_FOR_CHANGES"):
            answer, decision = by_answer.get(event.answer_id), event.decision
            if (
                answer is None
                or (answer.revision, answer.evidence_version) != (ar, ev)
                or decision is None
                or decision.case_id != case.pk
                or decision.answer_id != answer.pk
                or decision.evidence_version != ev
                or decision.action != event.action
            ):
                raise CaseConflict("case_history_inconsistent")
            stage = "ANSWERED" if event.action == "APPROVE" else "RETURNED_FOR_CHANGES"
            approved = answer.pk if event.action == "APPROVE" else None
        elif event.action not in ("INTAKE", "ROTATE_ACCESS", "REVOKE_ACCESS"):
            raise CaseConflict("case_history_inconsistent")
        if event.action not in ("APPROVE", "RETURN_FOR_CHANGES") and event.decision_id is not None:
            raise CaseConflict("case_history_inconsistent")
        if (event.stage, event.evidence_version, event.answer_revision) != (stage, ev, ar):
            raise CaseConflict("case_history_inconsistent")
    if (case.stage, case.evidence_version, case.answer_revision, case.approved_answer_id) != (
        stage,
        ev,
        ar,
        approved,
    ):
        raise CaseConflict("case_history_inconsistent")


def _event(case, action, subject_id, *, note="", answer=None, decision=None, initial=False):
    if not initial:
        case.revision += 1
        case.save(
            update_fields=[
                "stage",
                "revision",
                "evidence_version",
                "answer_revision",
                "approved_answer",
                "updated_at",
            ]
        )
    CaseEvent.objects.create(
        case=case,
        sequence=case.revision,
        action=action,
        stage=case.stage,
        evidence_version=case.evidence_version,
        answer_revision=case.answer_revision,
        subject_id=subject_id,
        note=note,
        answer=answer,
        decision=decision,
    )


def _ticket(case):
    token = "rt_" + secrets.token_urlsafe(32)
    RequesterTrackingToken.objects.create(
        case_id=case.tracking_id,
        token_sha256=_digest(token),
        expires_at=timezone.now() + timedelta(days=7),
    )
    return token


def _public(case):
    clarification = None
    if case.stage == "NEEDS_CLARIFICATION":
        event = case.events.filter(action="CLARIFICATION").order_by("-sequence").first()
        clarification = event.note if event else None
    # An approval is not a send, provider acknowledgement, or evidence of reading.
    return {
        "public_ref": case.public_ref,
        "status": case.stage,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "clarification": clarification,
        "delivery_verified": False,
        "read_confirmed": False,
    }


def _staff(case):
    result = _public(case)
    result.update(
        {
            "case_id": str(case.pk),
            "original_question": case.source.original_question,
            "source_channel": case.source.channel,
            "followups": [
                {"version": e.version, "text": e.text}
                for e in case.evidence.filter(version__gt=1).order_by("version")
            ],
            "answers": [
                {
                    "id": str(a.pk),
                    "revision": a.revision,
                    "evidence_version": a.evidence_version,
                    "text": a.text,
                }
                for a in case.answers.order_by("revision")
            ],
            "clarifications": list(
                case.events.filter(action="CLARIFICATION")
                .order_by("sequence")
                .values_list("note", flat=True)
            ),
            "approved_answer_id": str(case.approved_answer_id) if case.approved_answer_id else None,
        }
    )
    return result


@mutation_service
def intake_case(
    *,
    original_question,
    source_event_id,
    requester_id,
    idempotency_key,
    synthetic_fixtures_only=False,
):
    """Save an exact original once. Requester identity comes from the server session."""
    _text(original_question)
    if not all(_ref(v) for v in (source_event_id, requester_id, idempotency_key)):
        raise CaseConflict("invalid_intake_identity")
    _guard(synthetic_fixtures_only)
    digest = _digest(
        json.dumps(
            [original_question, source_event_id, requester_id, idempotency_key], ensure_ascii=False
        )
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            for key in sorted(
                ["intake:" + requester_id + ":" + idempotency_key, "source:" + source_event_id]
            ):
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,209))", [key])
        existing = (
            Case.objects.select_for_update()
            .filter(requester_id=requester_id, idempotency_key=idempotency_key)
            .first()
        )
        if existing:
            if existing.intake_sha256 != digest:
                raise CaseConflict("intake_idempotency_mismatch")
            _verify(existing)
            return {
                **_public(existing),
                "case_id": str(existing.pk),
                "token": None,
                "created": False,
            }
        if CaseSource.objects.filter(source_event_id=source_event_id).exists():
            raise CaseConflict("source_event_already_recorded")
        case_id = uuid.uuid4()
        tracking = RequesterTrackingCase.objects.create(
            case_key="case:" + str(case_id), registered_by="website-intake"
        )
        RequesterTrackingEvent.objects.create(
            case=tracking, sequence=1, old_stage="", new_stage="RECEIVED", actor_id="website-intake"
        )
        case = Case.objects.create(
            id=case_id,
            public_ref=f"FT-{timezone.now().year}-{secrets.token_hex(10).upper()}",
            requester_id=requester_id,
            idempotency_key=idempotency_key,
            intake_sha256=digest,
            tracking=tracking,
        )
        text_hash = _digest(original_question)
        CaseSource.objects.create(
            case=case,
            source_event_id=source_event_id,
            original_question=original_question,
            question_sha256=text_hash,
        )
        CaseEvidence.objects.create(
            case=case, version=1, kind="ORIGINAL", text=original_question, text_sha256=text_hash
        )
        _event(case, "INTAKE", requester_id, initial=True)
        token = _ticket(case)
        return {**_public(case), "case_id": str(case.pk), "token": token, "created": True}


@contextmanager
def _staff_case(
    case_id, subject_id, provider, ack, *, expected_revision=None, expected_evidence_version=None
):
    _guard(ack)
    before_case = _case(case_id)
    before = _identity(provider, subject_id, before_case)
    with transaction.atomic():
        case = _case(case_id, lock=True)
        identity = _identity(provider, subject_id, case)
        if before.auth_epoch != identity.auth_epoch:
            raise CaseConflict("case_identity_changed")
        _verify(case)
        if expected_revision is not None:
            _versions(case, expected_revision, expected_evidence_version)
        with _answer_use_boundary():
            yield case, identity


@mutation_service
def read_case(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        return _staff(case)


@mutation_service
def list_cases(*, subject_id, provider, synthetic_fixtures_only=False):
    _guard(synthetic_fixtures_only)
    try:
        identity = resolve_identity(provider, subject_id)
    except IdentityUnavailable as exc:
        raise CaseConflict("case_access_denied") from exc
    # Each scoped read re-resolves the provider; identity changes fail closed.
    rows = list(
        Case.objects.filter(public_ref__in=identity.case_keys)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [
        read_case(
            case_id=pk, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
        )
        for pk in rows
    ]


@mutation_service
def save_answer(
    *,
    case_id,
    subject_id,
    provider,
    text,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    _text(text)
    _mutation_versions(expected_revision, expected_evidence_version)
    with _staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, identity):
        case.answer_revision += 1
        answer = AnswerRevision.objects.create(
            case=case,
            revision=case.answer_revision,
            evidence_version=case.evidence_version,
            text=text,
            text_sha256=_digest(text),
            subject_id=identity.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=identity.auth_epoch,
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        _event(case, "SAVE_ANSWER", identity.subject_id, answer=answer)
        return _staff(case)


@mutation_service
def request_clarification(
    *,
    case_id,
    subject_id,
    provider,
    text,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    _text(text)
    _mutation_versions(expected_revision, expected_evidence_version)
    with _staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, identity):
        case.stage, case.approved_answer = "NEEDS_CLARIFICATION", None
        _event(case, "CLARIFICATION", identity.subject_id, note=text)
        return _staff(case)


@mutation_service
def record_decision(
    *,
    case_id,
    subject_id,
    provider,
    answer_id,
    action,
    note="",
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    _text(note, optional=True)
    _mutation_versions(expected_revision, expected_evidence_version)
    if action not in ("APPROVE", "RETURN_FOR_CHANGES") or (
        action == "RETURN_FOR_CHANGES" and not note.strip()
    ):
        raise CaseConflict("invalid_case_decision")
    with _staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, identity):
        answer = case.answers.filter(
            pk=_uuid(answer_id),
            revision=case.answer_revision,
            evidence_version=case.evidence_version,
        ).first()
        if answer is None or case.stage == "NEEDS_CLARIFICATION":
            raise CaseConflict("current_answer_required")
        if CaseDecision.objects.filter(answer=answer).exists():
            raise CaseConflict("answer_already_decided")
        # The human decision covers every immutable part of this exact revision,
        # even if the optional editing UI is disabled after a draft was created.
        approval_provider_id = provider.provider_id
        _answer_manifest(answer)
        if action == "APPROVE":
            from apps.answer_media.services import validate_for_approval

            _answer_citations(answer)
            _answer_timed(answer, actor=identity, provider=provider)
            validate_for_approval(answer)
        current_identity = _identity(provider, subject_id, case)
        if (current_identity.subject_id, current_identity.auth_epoch, provider.provider_id) != (
            identity.subject_id,
            identity.auth_epoch,
            approval_provider_id,
        ):
            raise CaseConflict("case_identity_changed")
        decision = CaseDecision.objects.create(
            case=case,
            answer=answer,
            evidence_version=case.evidence_version,
            action=action,
            note=note,
            subject_id=identity.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=identity.auth_epoch,
        )
        case.stage = "ANSWERED" if action == "APPROVE" else "RETURNED_FOR_CHANGES"
        case.approved_answer = answer if action == "APPROVE" else None
        _event(case, action, identity.subject_id, note=note, answer=answer, decision=decision)
        return _staff(case)


@contextmanager
def _token_case(token, ack):
    if type(token) is not str or _TOKEN.fullmatch(token) is None:
        raise CaseConflict("case_token_invalid_or_expired")
    _guard(ack)
    digest = _digest(token)
    grant = RequesterTrackingToken.objects.filter(pk=digest).first()
    if grant is None:
        raise CaseConflict("case_token_invalid_or_expired")
    with transaction.atomic():
        case = Case.objects.select_for_update().filter(tracking_id=grant.case_id).first()
        # Re-read after acquiring the same case lock used by rotation/revocation.
        grant = RequesterTrackingToken.objects.filter(pk=digest).first()
        if (
            case is None
            or grant is None
            or grant.case_id != case.tracking_id
            or grant.revoked_at is not None
            or grant.expires_at <= timezone.now()
        ):
            raise CaseConflict("case_token_invalid_or_expired")
        _verify(case)
        with _answer_use_boundary():
            yield case


@mutation_service
def requester_status(token, *, synthetic_fixtures_only=False):
    with _token_case(token, synthetic_fixtures_only) as case:
        return _public(case)


@mutation_service
def add_followup(*, token, text, expected_revision, synthetic_fixtures_only=False):
    _text(text)
    with _token_case(token, synthetic_fixtures_only) as case:
        _versions(case, expected_revision)
        case.evidence_version += 1
        CaseEvidence.objects.create(
            case=case,
            version=case.evidence_version,
            kind="FOLLOWUP",
            text=text,
            text_sha256=_digest(text),
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        _event(case, "FOLLOWUP", case.requester_id)
        return _public(case)


def _access(*, case_id, subject_id, provider, requester_id, rotate, synthetic_fixtures_only):
    with _staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, identity):
        if not _ref(requester_id) or requester_id != case.requester_id:
            raise CaseConflict("requester_recovery_identity_mismatch")
        _versions(case, case.revision)
        RequesterTrackingToken.objects.filter(
            case_id=case.tracking_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        token = _ticket(case) if rotate else None
        _event(case, "ROTATE_ACCESS" if rotate else "REVOKE_ACCESS", identity.subject_id)
        return {**_public(case), "token": token}


@mutation_service
def rotate_access(*, case_id, subject_id, provider, requester_id, synthetic_fixtures_only=False):
    return _access(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        requester_id=requester_id,
        rotate=True,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )


@mutation_service
def revoke_access(*, case_id, subject_id, provider, requester_id, synthetic_fixtures_only=False):
    return _access(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        requester_id=requester_id,
        rotate=False,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
