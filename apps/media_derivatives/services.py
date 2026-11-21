"""Durable finite jobs; decode between two short authorization transactions."""

import uuid
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from apps.casework import services as cases
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service
from apps.staff_mfa import integration as mfa
from apps.staff_sessions import services as sessions
from apps.staff_sessions.models import SessionRevocation

from . import execution, policy, sources
from .ledger import digest, seal, verify
from .models import DerivativeEvent, DerivativeJob, DerivedOutput

MAX_ATTEMPTS = 4
MAX_JOBS = 64
MAX_EVENTS = 24
LEASE_SECONDS = 60


def _history(job):
    events = list(job.events.order_by("sequence"))
    previous = "0" * 64
    if not events or len(events) > MAX_EVENTS:
        raise cases.CaseConflict("derivative_history_invalid")
    for number, row in enumerate(events, 1):
        verify(row)
        if (
            row.sequence != number
            or row.previous_digest != previous
            or row.provider_id != job.provider_id
            or row.subject_id != job.subject_id
            or row.auth_epoch != job.auth_epoch
        ):
            raise cases.CaseConflict("derivative_history_invalid")
        previous = row.digest
    return events


def _job(guard, identifier):
    row = DerivativeJob.objects.filter(
        pk=cases._uuid(identifier),
        case=guard.case,
        provider_id=guard.provider.provider_id,
        subject_id=guard.actor.subject_id,
    ).first()
    if row is None:
        raise cases.CaseConflict("derivative_job_unavailable")
    verify(row)
    if row.source_digest != digest(row.source) or row.recipe_version != execution.RECIPE_VERSION:
        raise cases.CaseConflict("derivative_original_changed")
    return row


def _source(job):
    return sources.Source(job.source["kind"], job.source["id"])


def _read(guard, job, action):
    pin, raw = sources.read(guard, _source(job), action=action, task=job.task)
    if pin != job.source:
        raise cases.CaseConflict("derivative_original_changed")
    return raw


def _origin(guard, job):
    """A persistent revocation veto, never a borrowed request/session grant."""
    if (
        job.execute_until <= timezone.now()
        or guard.actor.auth_epoch != job.auth_epoch
        or digest(policy.claims(guard.actor)) != job.claims_digest
    ):
        raise cases.CaseConflict("derivative_execution_expired")
    guard.deadline = min(guard.deadline, job.execute_until)
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if job.origin_session_id is not None:
        try:
            authority = sessions.configured(directory)
            row = sessions.get(str(job.origin_session_id), lock=True)
            expected = (row.digest, sessions.epoch(authority), sessions.runtime_digest())

            def check():
                current = sessions.get(str(row.pk))
                if (
                    sessions.configured(directory) is not authority
                    or (current.digest, sessions.epoch(authority), sessions.runtime_digest())
                    != expected
                    or current.runtime_digest != expected[2]
                    or current.claims_digest != sessions.digest(sessions.claims(guard.actor))
                    or current.provider_id != job.provider_id
                    or current.subject_id != job.subject_id
                    or current.auth_epoch != job.auth_epoch
                    or current.surface != "CASEWORK"
                    or current.expires_at <= timezone.now()
                    or SessionRevocation.objects.filter(session=current).exists()
                ):
                    raise cases.CaseConflict("derivative_origin_session_revoked")

            def use():
                try:
                    sessions.permit(
                        authority, directory, guard.actor, "USE", sessions.resource(row)
                    )
                except IdentityUnavailable as exc:
                    raise cases.CaseConflict("derivative_origin_session_revoked") from exc

            use()
            check()
            guard.callbacks.append(use)
            guard.source_checks.append(check)
            guard.deadline = min(guard.deadline, row.expires_at)
        except IdentityUnavailable as exc:
            raise cases.CaseConflict("derivative_origin_session_revoked") from exc
    elif getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is True:
        # Enabling server session governance cannot revive an unbound old job.
        raise cases.CaseConflict("derivative_origin_session_required")
    _origin_mfa(guard, job, directory)


def _origin_mfa(guard, job, directory):
    """Keep the exact issued factor as a persistent execution veto.

    No browser binding, new proof, request lease or identity is manufactured here.
    A stored factor still vetoes execution when MFA or its app is later disabled.
    This adds no derivative or original-source permission.
    """
    try:
        use = None
        if mfa.enabled():
            # Older profiles may not install MFA models. Reject misconfiguration
            # before importing them, rather than silently falling back to legacy.
            mfa.fields()
            from apps.staff_mfa.models import SessionAssurance

            assurance = SessionAssurance.objects.filter(session_id=job.origin_session_id).first()
            if assurance is None:
                raise IdentityUnavailable("staff_mfa_session_proof_required")
            use = mfa.capture(
                provider=directory,
                actor=guard.actor,
                session_id=str(job.origin_session_id),
                proof_id=str(assurance.proof_id),
            )
            guard.deadline = min(guard.deadline, use.deadline)
        else:
            mfa.legacy(directory.provider_id, guard.actor.subject_id)

        def check(*, authorize=False):
            try:
                mfa.check(use, provider=directory, actor=guard.actor, authorize=authorize)
            except IdentityUnavailable as exc:
                raise cases.CaseConflict("derivative_origin_mfa_revoked") from exc

        if use is not None:
            guard.callbacks.append(lambda: check(authorize=True))
        # Also retain the legacy history veto while CPU work is outside the DB;
        # a new enrollment cannot be ignored by a formerly legacy queued job.
        guard.source_checks.append(check)
        check()
    except IdentityUnavailable as exc:
        raise cases.CaseConflict("derivative_origin_mfa_revoked") from exc


def _event(
    guard,
    job,
    *,
    action,
    state,
    request_key,
    attempt,
    lease=None,
    lease_until=None,
    output=None,
    code,
    engine=None,
):
    previous = job.events.order_by("-sequence").first()
    if previous:
        verify(previous)
    sequence = previous.sequence + 1 if previous else 1
    if sequence > MAX_EVENTS:
        raise cases.CaseConflict("derivative_history_bound")
    return seal(
        DerivativeEvent(
            job=job,
            sequence=sequence,
            request_key=cases._uuid(request_key),
            action=action,
            state=state,
            attempt=attempt,
            lease=lease,
            lease_until=lease_until,
            output=output,
            code=code,
            engine=engine or {},
            provider_id=job.provider_id,
            subject_id=job.subject_id,
            auth_epoch=job.auth_epoch,
            previous_digest=previous.digest if previous else "0" * 64,
        )
    )


def _dto(job, last):
    state = last.state
    if state in {"QUEUED", "RUNNING"} and (
        job.execute_until <= timezone.now()
        or (last.lease_until and last.lease_until <= timezone.now())
    ):
        state = "EXPIRED"
    owner = job.attachment or job.answer_part or job.library_version
    labels = {
        "QUEUED": "في الانتظار",
        "RUNNING": "قيد المعالجة",
        "READY": "جاهزة",
        "FAILED": "تعذرت المعالجة",
        "UNAVAILABLE": "المعالج غير متاح",
        "CANCELLED": "ملغاة",
        "EXPIRED": "انتهت مهلة التنفيذ",
    }
    return {
        "id": str(job.pk),
        "task": job.task,
        "source": job.source,
        "state": state,
        "state_label": labels[state],
        "label": owner.filename,
        "recorded_state": last.state,
        "code": last.code,
        "sequence": last.sequence,
        "attempt": last.attempt,
        "output_id": str(last.output_id) if last.output_id else "",
        "execute_until": job.execute_until,
        "recipe_version": job.recipe_version,
        "transcription": "UNAVAILABLE_NO_PROVIDER",
    }


def _task(task):
    if task not in execution.TASKS:
        raise cases.CaseConflict("derivative_task_invalid")


@mutation_service
def prepare(*, source, task, request_key, expected_revision, expected_evidence_version, **common):
    _task(task)
    if type(source) is not sources.Source:
        raise cases.CaseConflict("derivative_source_invalid")
    source.validated()
    key = cases._uuid(request_key)
    requested = digest(
        [source.kind, source.identifier, task, expected_revision, expected_evidence_version]
    )
    with policy.boundary(**common) as guard:
        existing = DerivativeJob.objects.filter(
            case=guard.case,
            provider_id=guard.provider.provider_id,
            subject_id=guard.actor.subject_id,
            request_key=key,
        ).first()
        if existing:
            verify(existing)
            if existing.request_digest != requested:
                raise cases.CaseConflict("derivative_idempotency_conflict")
            _read(guard, existing, "CREATE")
            return _dto(existing, _history(existing)[-1])
        cases._mutation_versions(expected_revision, expected_evidence_version)
        cases._versions(guard.case, expected_revision, expected_evidence_version)
        if DerivativeJob.objects.filter(case=guard.case).count() >= MAX_JOBS:
            raise cases.CaseConflict("derivative_job_capacity")
        pin, _ = sources.read(guard, source, action="CREATE", task=task)
        session_id = None
        if getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is True:
            from apps.casework_web.access import RequestDirectory

            if type(guard.provider) is not RequestDirectory or guard.provider._session is None:
                raise cases.CaseConflict("derivative_request_session_required")
            sessions.check(guard.provider._session, actor=guard.actor, authorize=False)
            session_id = guard.provider._session.id
        job = seal(
            DerivativeJob(
                case=guard.case,
                **sources.fields(source),
                origin_session_id=session_id,
                provider_id=guard.provider.provider_id,
                subject_id=guard.actor.subject_id,
                auth_epoch=guard.actor.auth_epoch,
                claims_digest=digest(policy.claims(guard.actor)),
                source=pin,
                source_digest=digest(pin),
                task=task,
                recipe_version=execution.RECIPE_VERSION,
                request_key=key,
                request_digest=requested,
                execute_until=min(guard.deadline, timezone.now() + timedelta(minutes=10)),
            )
        )
        event = _event(
            guard, job, action="CREATE", state="QUEUED", request_key=key, attempt=0, code="QUEUED"
        )
        return _dto(job, event)


@mutation_service
def status(*, job_id, **common):
    with policy.boundary(**common) as guard:
        job = _job(guard, job_id)
        _read(guard, job, "READ")
        return _dto(job, _history(job)[-1])


@mutation_service
def command(*, job_id, action, request_key, expected_sequence, **common):
    if (
        action not in {"CANCEL", "RETRY"}
        or type(expected_sequence) is not int
        or not 1 <= expected_sequence <= MAX_EVENTS
    ):
        raise cases.CaseConflict("derivative_command_invalid")
    key = cases._uuid(request_key)
    with policy.boundary(**common) as guard:
        job = _job(guard, job_id)
        _read(guard, job, action)
        last = _history(job)[-1]
        previous = job.events.filter(request_key=key).first()
        if previous:
            if previous.action != action or previous.sequence != expected_sequence + 1:
                raise cases.CaseConflict("derivative_idempotency_conflict")
            return _dto(job, last)
        if last.sequence != expected_sequence:
            raise cases.CaseConflict("derivative_sequence_changed")
        if action == "CANCEL":
            if last.state not in {"QUEUED", "RUNNING", "FAILED", "UNAVAILABLE"}:
                raise cases.CaseConflict("derivative_cancel_invalid")
            event = _event(
                guard,
                job,
                action=action,
                state="CANCELLED",
                request_key=key,
                attempt=last.attempt,
                code="USER_CANCELLED",
            )
        else:
            _origin(guard, job)
            stale = last.state == "RUNNING" and last.lease_until <= timezone.now()
            if (
                last.state not in {"FAILED", "UNAVAILABLE"} and not stale
            ) or last.attempt >= MAX_ATTEMPTS:
                raise cases.CaseConflict("derivative_retry_invalid")
            event = _event(
                guard,
                job,
                action=action,
                state="QUEUED",
                request_key=key,
                attempt=last.attempt,
                code="REQUEUED",
            )
        return _dto(job, event)


def _claim(guard, job):
    _origin(guard, job)
    last = _history(job)[-1]
    if last.state != "QUEUED" or last.attempt >= MAX_ATTEMPTS:
        raise cases.CaseConflict("derivative_not_queued")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(761135, 1)")
    latest = (
        DerivativeEvent.objects.filter(job_id=OuterRef("job_id"))
        .order_by("-sequence")
        .values("sequence")[:1]
    )
    if DerivativeEvent.objects.filter(
        state="RUNNING", lease_until__gt=timezone.now(), sequence=Subquery(latest)
    ).exists():
        raise cases.CaseConflict("derivative_worker_busy")
    return _event(
        guard,
        job,
        action="CLAIM",
        state="RUNNING",
        request_key=uuid.uuid4(),
        attempt=last.attempt + 1,
        lease=uuid.uuid4(),
        lease_until=min(job.execute_until, timezone.now() + timedelta(seconds=LEASE_SECONDS)),
        code="RUNNING",
    )


@mutation_service
def run_job(*, job_id, **common):
    if connection.in_atomic_block:
        raise cases.CaseConflict("derivative_worker_outer_transaction_forbidden")
    with policy.boundary(**common) as before:
        job = _job(before, job_id)
        raw = _read(before, job, "EXECUTE")
        claimed = _claim(before, job)
        configured = getattr(settings, "FATWA_MEDIA_DERIVATIVES_PROCESSOR", None)
        initial_configuration = before.config
    # A no-longer-current policy cannot reach the local process. This also pins
    # privacy, source scans and a recorded origin-session veto across execution.
    before.check()

    def cancelled():
        try:
            before.check()
            current = job.events.order_by("-sequence").first()
            return (
                current is None
                or current.pk != claimed.pk
                or current.lease != claimed.lease
                or current.state != "RUNNING"
                or current.lease_until <= timezone.now()
            )
        except (cases.CaseConflict, IdentityUnavailable):
            return True

    result = (
        configured.run(raw, media_type=job.source["media_type"], task=job.task, cancelled=cancelled)
        if type(configured) is execution.FFmpegProcessor
        else execution.Outcome("UNAVAILABLE", "PROCESSOR_UNAVAILABLE")
    )
    # No object from an executor has a persistence callback. A stale/denied
    # completion is simply discarded; the durable claim becomes lease-expired.
    with policy.boundary(**common) as after:
        current = _job(after, job.pk)
        _read(after, current, "EXECUTE")
        _origin(after, current)
        last = _history(current)[-1]
        if last.state == "CANCELLED":
            return _dto(current, last)
        if (
            last.pk != claimed.pk
            or last.lease != claimed.lease
            or last.state != "RUNNING"
            or last.lease_until <= timezone.now()
            or after.config != initial_configuration
            or current.digest != job.digest
        ):
            raise cases.CaseConflict("derivative_completion_stale")
        before.check()
        if type(result) is not execution.Outcome or result.status not in {
            "READY",
            "FAILED",
            "UNAVAILABLE",
            "CANCELLED",
        }:
            raise cases.CaseConflict("derivative_worker_contract_invalid")
        output = None
        if result.status == "READY":
            execution.validate_output(result.raw, result.media_type, result.metadata)
            output = seal(
                DerivedOutput(
                    job=current,
                    attempt=last.attempt,
                    lease=last.lease,
                    source_digest=current.source_digest,
                    recipe_version=current.recipe_version,
                    sha256=sha256(result.raw).hexdigest(),
                    size=len(result.raw),
                    raw=result.raw,
                    media_type=result.media_type,
                    metadata=result.metadata,
                    engine=result.engine,
                )
            )
        state = "FAILED" if result.status == "CANCELLED" else result.status
        event = _event(
            after,
            current,
            action="COMPLETE" if state == "READY" else "FAIL",
            state=state,
            request_key=uuid.uuid4(),
            attempt=last.attempt,
            lease=last.lease,
            lease_until=last.lease_until,
            output=output,
            code=result.code,
            engine=result.engine,
        )
        return _dto(current, event)


@mutation_service
def original(*, job_id, **common):
    with policy.boundary(**common) as guard:
        job = _job(guard, job_id)
        raw = _read(guard, job, "READ")
        _history(job)
        return {"raw": raw, "media_type": job.source["media_type"], "sha256": job.source["sha256"]}


@mutation_service
def _output(*, job_id, action, **common):
    with policy.boundary(**common) as guard:
        job = _job(guard, job_id)
        _read(guard, job, action)
        last = _history(job)[-1]
        if last.state != "READY" or last.output_id is None:
            raise cases.CaseConflict("derivative_not_ready")
        row = last.output
        verify(row)
        raw = bytes(row.raw)
        if (
            row.job_id != job.pk
            or row.attempt != last.attempt
            or row.lease != last.lease
            or row.source_digest != job.source_digest
            or row.recipe_version != job.recipe_version
            or row.engine != last.engine
            or len(raw) != row.size
            or sha256(raw).hexdigest() != row.sha256
        ):
            raise cases.CaseConflict("derivative_output_invalid")
        execution.validate_output(raw, row.media_type, row.metadata)
        return {
            "raw": raw,
            "media_type": row.media_type,
            "sha256": row.sha256,
            "metadata": row.metadata,
            "engine": row.engine,
            "source": job.source,
        }


@mutation_service
def read_output(*, job_id, **common):
    return _output(job_id=job_id, action="READ", **common)


@mutation_service
def download(*, job_id, **common):
    return _output(job_id=job_id, action="DOWNLOAD", **common)


@mutation_service
def can_download(*, job_id, **common):
    try:
        with policy.boundary(**common) as guard:
            job = _job(guard, job_id)
            _read(guard, job, "DOWNLOAD")
            last = _history(job)[-1]
            return last.state == "READY" and last.output_id is not None
    except cases.CaseConflict:
        return False


@mutation_service
def inventory(**common):
    """Authorized source choices and jobs; excluded rows never enter counts/DTOs."""
    from apps.answer_media.models import AnswerPart
    from apps.case_attachments.models import CaseAttachment
    from apps.research_library.models import LibraryVersion

    with policy.response_projection():
        with policy.boundary(**common) as guard:
            case_id, ref = guard.case.pk, guard.case.public_ref
            revision, evidence = guard.case.revision, guard.case.evidence_version
            identity = (guard.provider.provider_id, guard.actor.subject_id)
        candidates = (
            [
                sources.Source("ATTACHMENT", str(value))
                for value in CaseAttachment.objects.filter(case_id=case_id)
                .order_by("created_at")
                .values_list("pk", flat=True)[:32]
            ]
            + [
                sources.Source("ANSWER_PART", str(value))
                for value in AnswerPart.objects.filter(
                    manifest__answer__case_id=case_id, ordinal__gt=1
                )
                .order_by("created_at")
                .values_list("pk", flat=True)[:16]
            ]
            + [
                sources.Source("LIBRARY_VERSION", str(value))
                for value in LibraryVersion.objects.filter(
                    item__case_id=case_id, blob__isnull=False
                )
                .order_by("created_at")
                .values_list("pk", flat=True)[:16]
            ]
        )
        choices = []
        for source in candidates:
            for task in sorted(execution.TASKS):
                try:
                    with policy.boundary(**common) as guard:
                        pin, _ = sources.read(guard, source, action="CREATE", task=task)
                        choices.append(
                            {
                                "source": source.kind + ":" + source.identifier,
                                "task": task,
                                "pin": pin,
                                "label": sources._owner(guard, source).filename,
                            }
                        )
                except cases.CaseConflict:
                    continue
        jobs = []
        for identifier in (
            DerivativeJob.objects.filter(
                case_id=case_id, provider_id=identity[0], subject_id=identity[1]
            )
            .order_by("-created_at")
            .values_list("pk", flat=True)[:MAX_JOBS]
        ):
            try:
                jobs.append(status(job_id=identifier, **common))
            except cases.CaseConflict:
                continue
        return {
            "case_ref": ref,
            "revision": revision,
            "evidence_version": evidence,
            "choices": choices,
            "jobs": jobs,
            "transcription": "UNAVAILABLE_NO_PROVIDER",
        }
