"""Durable selected exports. A stored artifact never replaces current authorization."""

import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context, mutation_service
from apps.research_workspace import services as research

from . import policy, resources
from .models import ExportArtifact, ExportEvent, ExportJob
from .serialization import archive, data_file, digest

MAX_ITEMS = 20
MAX_JOBS = 32
EVENT_LIMITS = {
    "PREPARE": 1,
    "QUEUE": 92,
    "START": 93,
    "READY": 94,
    "PARTIAL": 94,
    "FAIL": 94,
    "DOWNLOAD": 94,
    "CANCEL": 95,
    "EXPIRE": 96,
}
ZERO = "0" * 64
MISSING = {"private_original_integrity_failed", "private_storage_unavailable"}
STATES = {
    "PREPARED": "معاينة محفوظة؛ لم يبدأ التصدير",
    "QUEUED": "جاهز للتجهيز",
    "RUNNING": "جارٍ تجهيز المحاولة",
    "READY": "اكتمل النطاق المطلوب",
    "PARTIAL": "نتيجة جزئية؛ توجد ملفات تعذرت",
    "FAILED": "لم تكتمل المحاولة",
    "CANCELLED": "ألغيت المهمة",
    "EXPIRED": "انتهت مدة المهمة والتنزيل",
}


def _event_data(event):
    return {
        key: str(value)
        if isinstance(value, uuid.UUID)
        else value.isoformat()
        if hasattr(value, "isoformat")
        else value
        for key in (
            "job_id",
            "sequence",
            "request_key",
            "action",
            "state",
            "attempt",
            "lease_id",
            "lease_until",
            "completed",
            "outcomes",
            "artifact_sha256",
            "subject_id",
            "provider_id",
            "auth_epoch",
            "previous_sha256",
        )
        if (value := getattr(event, key)) is not None
    }


def _history(job):
    events = list(job.events.order_by("sequence")[:97])
    previous = ZERO
    for number, event in enumerate(events, 1):
        if (
            event.sequence != number
            or event.previous_sha256 != previous
            or event.sha256 != digest(_event_data(event))
            or event.subject_id != job.subject_id
            or event.provider_id != job.provider_id
        ):
            raise cases.CaseConflict("export_history_invalid")
        previous = event.sha256
    if not events or len(events) > 96:
        raise cases.CaseConflict("export_history_invalid")
    return events


def _scope_digest(job):
    return digest(
        {
            "selection": job.selection,
            "format": job.format,
            "include_files": job.include_files,
            "case_revision": job.case_revision,
            "evidence_version": job.evidence_version,
        }
    )


def _get(case, actor, provider, job_id):
    job = ExportJob.objects.filter(
        pk=cases._uuid(job_id),
        case=case,
        provider_id=provider.provider_id,
        subject_id=actor.subject_id,
    ).first()
    if job is None:
        raise cases.CaseConflict("export_job_unavailable")
    if (
        not isinstance(job.selection, list)
        or not 1 <= len(job.selection) <= MAX_ITEMS
        or job.selection_sha256 != _scope_digest(job)
    ):
        raise cases.CaseConflict("export_scope_invalid")
    for entry in job.selection:
        if type(entry) is not dict or set(entry) != {"resource", "record_sha256"}:
            raise cases.CaseConflict("export_scope_invalid")
        resources.resource(entry["resource"])
    return job


def _record(job, actor, provider, *, action, state, request_key, previous=None, **changes):
    if previous is None and job.events.exists():
        previous = _history(job)[-1]
    sequence = previous.sequence + 1 if previous else 1
    if sequence > EVENT_LIMITS.get(action, 0):
        raise cases.CaseConflict("export_history_capacity")
    values = dict(
        job=job,
        sequence=sequence,
        request_key=cases._uuid(request_key),
        action=action,
        state=state,
        attempt=previous.attempt if previous else 0,
        lease_id=previous.lease_id if previous else None,
        lease_until=previous.lease_until if previous else None,
        completed=previous.completed if previous else 0,
        outcomes=previous.outcomes if previous else [],
        artifact_sha256=previous.artifact_sha256 if previous else "",
        subject_id=actor.subject_id,
        provider_id=provider.provider_id,
        auth_epoch=actor.auth_epoch,
        previous_sha256=previous.sha256 if previous else ZERO,
    )
    values.update(changes)
    event = ExportEvent(**values)
    event.sha256 = digest(_event_data(event))
    event.save(force_insert=True)
    return event


def _current(job, actor, provider):
    event = _history(job)[-1]
    if job.expires_at <= timezone.now() and event.state != "EXPIRED":
        event = _record(
            job,
            actor,
            provider,
            action="EXPIRE",
            state="EXPIRED",
            request_key=uuid.uuid4(),
            previous=event,
        )
    return event


def _public(job, event):
    return {
        "id": str(job.pk),
        "revision": event.sequence,
        "state": event.state,
        "state_label": STATES[event.state],
        "format": job.format,
        "include_files": job.include_files,
        "requested": len(job.selection),
        "completed": event.completed,
        "attempt": event.attempt,
        "outcomes": event.outcomes,
        "expires_at": job.expires_at,
        "can_download": event.state in {"READY", "PARTIAL"}
        and event.sequence < EVENT_LIMITS["DOWNLOAD"],
        "can_queue": event.sequence < EVENT_LIMITS["QUEUE"]
        and event.attempt < 10
        and (
            event.state in {"PREPARED", "FAILED", "PARTIAL"}
            or event.state == "RUNNING"
            and event.lease_until <= timezone.now()
        ),
        "can_build": event.state == "QUEUED" and event.sequence < EVENT_LIMITS["START"],
        "can_cancel": event.state not in {"CANCELLED", "EXPIRED"},
        "history_capacity": event.sequence >= EVENT_LIMITS["DOWNLOAD"],
    }


@mutation_context
@contextmanager
def job_boundary(*, job_id, action="VIEW", source_policy=False, **common):
    with policy.boundary(**common, action=action) as (case, actor):
        job = _get(case, actor, common["provider"], job_id)
        if source_policy:
            kinds = {row["resource"]["kind"] for row in job.selection}
            with policy.boundary(**common, action=action, kinds=kinds):
                yield case, actor, job
        else:
            yield case, actor, job


def _read_selection(case, actor, provider, selection, include_files, *, allow_missing=False):
    records, files, outcomes = [], {}, []
    for ordinal, entry in enumerate(selection, 1):
        selected = resources.resource(entry["resource"])
        try:
            record, media = resources.read(
                case=case,
                actor=actor,
                provider=provider,
                selected=selected,
                ordinal=ordinal,
                include_files=include_files,
            )
        except cases.CaseConflict as exc:
            if not allow_missing or str(exc) not in MISSING or selected.kind not in resources.MEDIA:
                raise
            resources.unavailable_permission(case, actor, provider, selected, include_files)
            outcomes.append({"ordinal": ordinal, "status": "UNAVAILABLE"})
            continue
        if digest(record) != entry["record_sha256"]:
            raise cases.CaseConflict("export_source_version_changed")
        records.append(record)
        files.update(media)
        outcomes.append({"ordinal": ordinal, "status": "INCLUDED"})
    return records, files, outcomes


@mutation_service
def inventory(*, kind="REFERENCE", query="", edition_id=None, **common):
    if (
        kind not in {"REFERENCE", "TRANSCRIPT", "KNOWLEDGE", "MEDIA"}
        or type(query) is not str
        or len(query) > 80
    ):
        raise cases.CaseConflict("export_filter_invalid")
    kinds = resources.MEDIA if kind == "MEDIA" else {kind}
    with policy.boundary(**common, kinds=kinds) as (case, actor):
        result = research.search(**common, kind=kind, query=query, edition_id=edition_id)
        rows = []
        for row in result["results"][:MAX_ITEMS]:
            selected = resources.resource(row["resource"])
            try:
                record, _ = resources.read(
                    case=case,
                    actor=actor,
                    provider=common["provider"],
                    selected=selected,
                    ordinal=len(rows) + 1,
                    include_files=False,
                )
            except cases.CaseConflict as exc:
                if str(exc) == "export_not_authorized":
                    continue
                raise
            title = (
                record["metadata"].get("heading_title")
                or record["metadata"].get("title")
                or {
                    "TRANSCRIPT": "تفريغ مصدر مرتبط",
                    "ATTACHMENT": "مرفق خاص بالقضية",
                    "ANSWER_MEDIA": "جزء ملف من جواب القضية",
                }.get(selected.kind, "مادة مصرح بها")
            )
            rows.append({"resource": asdict(selected), "title": title, "kind": selected.kind})
        # Readers and all per-resource export grants are current across the whole
        # collection; a last callback cannot revoke an earlier displayed row.
        for ordinal, row in enumerate(rows, 1):
            resources.read(
                case=case,
                actor=actor,
                provider=common["provider"],
                selected=row["resource"],
                ordinal=ordinal,
                include_files=False,
            )
        return {
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "rows": rows,
            "kind": kind,
            "query": query,
            "edition_id": edition_id,
            "editions": result["editions"],
            "limited": len(result["results"]) > MAX_ITEMS or result["limited"],
        }


@mutation_service
def prepare(
    *,
    selected,
    format,
    include_files,
    request_key,
    expected_revision,
    expected_evidence_version,
    **common,
):
    if (
        type(selected) not in (list, tuple)
        or not 1 <= len(selected) <= MAX_ITEMS
        or format not in {"JSON", "CSV", "JSONL"}
        or type(include_files) is not bool
    ):
        raise cases.CaseConflict("export_selection_invalid")
    chosen = [resources.resource(value) for value in selected]
    if len({digest(asdict(value)) for value in chosen}) != len(chosen):
        raise cases.CaseConflict("export_duplicate_resource")
    with policy.boundary(**common, action="PREPARE", kinds={r.kind for r in chosen}) as (
        case,
        actor,
    ):
        cases._versions(case, expected_revision, expected_evidence_version)
        selection = []
        for ordinal, value in enumerate(chosen, 1):
            record, _ = resources.read(
                case=case,
                actor=actor,
                provider=common["provider"],
                selected=value,
                ordinal=ordinal,
                include_files=include_files,
            )
            selection.append(resources.pin(value, record))
        ttl = getattr(settings, "FATWA_SELECTED_EXPORTS_TTL_SECONDS", 1800)
        if type(ttl) is not int or not 1 <= ttl <= 1800:
            raise cases.CaseConflict("export_expiry_configuration")
        job = ExportJob(
            case=case,
            provider_id=common["provider"].provider_id,
            subject_id=actor.subject_id,
            request_key=cases._uuid(request_key),
            case_revision=case.revision,
            evidence_version=case.evidence_version,
            selection=selection,
            format=format,
            include_files=include_files,
            expires_at=timezone.now() + timedelta(seconds=ttl),
        )
        job.selection_sha256 = _scope_digest(job)
        existing = ExportJob.objects.filter(
            case=case,
            provider_id=job.provider_id,
            subject_id=actor.subject_id,
            request_key=job.request_key,
        ).first()
        if existing:
            if existing.selection_sha256 != job.selection_sha256:
                raise cases.CaseConflict("export_idempotency_conflict")
            job = existing
            event = _current(job, actor, common["provider"])
        else:
            if (
                ExportJob.objects.filter(
                    case=case, provider_id=job.provider_id, subject_id=actor.subject_id
                ).count()
                >= MAX_JOBS
            ):
                raise cases.CaseConflict("export_job_capacity")
            job.save(force_insert=True)
            event = _record(
                job,
                actor,
                common["provider"],
                action="PREPARE",
                state="PREPARED",
                request_key=request_key,
            )
        _read_selection(case, actor, common["provider"], job.selection, job.include_files)
        return _public(job, event)


@mutation_service
def jobs(**common):
    with policy.boundary(**common) as (case, actor):
        rows = ExportJob.objects.filter(
            case=case, provider_id=common["provider"].provider_id, subject_id=actor.subject_id
        ).order_by("-created_at")[:MAX_JOBS]
        return {
            "case_ref": case.public_ref,
            "jobs": [_public(job, _current(job, actor, common["provider"])) for job in rows],
        }


@mutation_service
def status(*, job_id, **common):
    with job_boundary(job_id=job_id, **common) as (_, actor, job):
        return _public(job, _current(job, actor, common["provider"]))


@mutation_service
def preview(*, job_id, **common):
    with job_boundary(job_id=job_id, action="PREPARE", source_policy=True, **common) as (
        case,
        actor,
        job,
    ):
        event = _current(job, actor, common["provider"])
        if event.state in {"CANCELLED", "EXPIRED"}:
            raise cases.CaseConflict("export_job_closed")
        records, files, outcomes = _read_selection(
            case, actor, common["provider"], job.selection, job.include_files, allow_missing=True
        )
        _, data = data_file(job.format, records)
        result = _public(job, event)
        result.update(
            preview=[
                {
                    "ordinal": row["ordinal"],
                    "kind": row["kind"],
                    "identifier": row["identifier"],
                    "version_sha256": row["version_sha256"],
                    "file_count": len(row["files"]),
                }
                for row in records
            ],
            preview_outcomes=outcomes,
            estimated_bytes=len(data) + sum(map(len, files.values())),
        )
        _read_selection(
            case, actor, common["provider"], job.selection, job.include_files, allow_missing=True
        )
        return result


@mutation_service
def command(*, job_id, action, request_key, expected_revision, **common):
    if action not in {"QUEUE", "CANCEL"}:
        raise cases.CaseConflict("export_command_invalid")
    with job_boundary(job_id=job_id, action="MANAGE", **common) as (_, actor, job):
        event = _current(job, actor, common["provider"])
        key = cases._uuid(request_key)
        replay = job.events.filter(request_key=key).first()
        if replay:
            if replay.action != action:
                raise cases.CaseConflict("export_idempotency_conflict")
            return _public(job, event)
        if type(expected_revision) is not int or expected_revision != event.sequence:
            raise cases.CaseConflict("export_version_changed")
        if event.state in {"EXPIRED", "CANCELLED"}:
            raise cases.CaseConflict("export_job_closed")
        if action == "QUEUE":
            if (
                event.attempt >= 10
                or event.state not in {"PREPARED", "FAILED", "PARTIAL"}
                and not (event.state == "RUNNING" and event.lease_until <= timezone.now())
            ):
                raise cases.CaseConflict("export_retry_unavailable")
            state = "QUEUED"
            values = {
                "completed": 0,
                "outcomes": [],
                "artifact_sha256": "",
                "lease_id": None,
                "lease_until": None,
            }
        else:
            state, values = "CANCELLED", {}
        event = _record(
            job,
            actor,
            common["provider"],
            action=action,
            state=state,
            request_key=key,
            previous=event,
            **values,
        )
        return _public(job, event)


def _claim(job_id, request_key, common):
    with job_boundary(job_id=job_id, action="GENERATE", source_policy=True, **common) as (
        _,
        actor,
        job,
    ):
        event = _current(job, actor, common["provider"])
        prior = job.events.filter(request_key=cases._uuid(request_key)).first()
        if prior:
            if prior.action != "START":
                raise cases.CaseConflict("export_idempotency_conflict")
            return None, _public(job, event)
        if event.state != "QUEUED" or event.attempt >= 10:
            raise cases.CaseConflict("export_not_queued")
        lease_seconds = getattr(settings, "FATWA_SELECTED_EXPORTS_LEASE_SECONDS", 120)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 120:
            raise cases.CaseConflict("export_lease_configuration")
        lease = uuid.uuid4()
        event = _record(
            job,
            actor,
            common["provider"],
            action="START",
            state="RUNNING",
            request_key=request_key,
            previous=event,
            attempt=event.attempt + 1,
            lease_id=lease,
            lease_until=timezone.now() + timedelta(seconds=lease_seconds),
        )
        return lease, _public(job, event)


def _failure(job_id, lease, common):
    # Record only a generic failure against the authenticated claim. Loss of an
    # export grant cannot leave a falsely successful artifact. This private
    # completion does not read source data or grant download access.
    with (
        synthetic_queue_atomic(),
        cases._staff_case(
            common["case_id"],
            common["subject_id"],
            common["provider"],
            common["synthetic_fixtures_only"],
        ) as (case, actor),
    ):
        job = _get(case, actor, common["provider"], job_id)
        event = _current(job, actor, common["provider"])
        if event.state == "RUNNING" and event.lease_id == lease:
            event = _record(
                job,
                actor,
                common["provider"],
                action="FAIL",
                state="FAILED",
                request_key=uuid.uuid4(),
                previous=event,
                completed=0,
                artifact_sha256="",
                outcomes=[
                    {"ordinal": i, "status": "FAILED"} for i in range(1, len(job.selection) + 1)
                ],
            )
        return _public(job, event)


@mutation_service
def run_job(*, job_id, request_key, **common):
    lease, initial = _claim(job_id, request_key, common)
    if lease is None:
        return initial
    try:
        with job_boundary(job_id=job_id, action="GENERATE", source_policy=True, **common) as (
            case,
            actor,
            job,
        ):
            event = _current(job, actor, common["provider"])
            if (
                event.state != "RUNNING"
                or event.lease_id != lease
                or event.lease_until <= timezone.now()
            ):
                raise cases.CaseConflict("export_lease_changed")
            records, files, outcomes = _read_selection(
                case,
                actor,
                common["provider"],
                job.selection,
                job.include_files,
                allow_missing=True,
            )
            if not records:
                raise cases.CaseConflict("export_no_available_records")
            raw, manifest = archive(job=job, records=records, files=files, outcomes=outcomes)
            # Exact source recheck occurs after serialization, before committing
            # artifact bytes; final policy/ledger checks occur on boundary exit.
            final = _read_selection(
                case,
                actor,
                common["provider"],
                job.selection,
                job.include_files,
                allow_missing=True,
            )
            if (records, files, outcomes) != final:
                raise cases.CaseConflict("export_source_changed_during_build")
            artifact = ExportArtifact.objects.create(
                job=job,
                attempt=event.attempt,
                raw=raw,
                sha256=sha256(raw).hexdigest(),
                size=len(raw),
                manifest=manifest,
            )
            state = "READY" if len(records) == len(job.selection) else "PARTIAL"
            event = _record(
                job,
                actor,
                common["provider"],
                action=state,
                state=state,
                request_key=uuid.uuid4(),
                previous=event,
                completed=len(records),
                outcomes=outcomes,
                artifact_sha256=artifact.sha256,
            )
            return _public(job, event)
    except cases.CaseConflict:
        return _failure(job_id, lease, common)


@mutation_service
def download(*, job_id, request_key, **common):
    with job_boundary(job_id=job_id, action="DOWNLOAD", source_policy=True, **common) as (
        case,
        actor,
        job,
    ):
        event = _current(job, actor, common["provider"])
        if event.state not in {"READY", "PARTIAL"}:
            raise cases.CaseConflict("export_download_unavailable")
        artifact = job.artifacts.filter(attempt=event.attempt).first()
        if (
            artifact is None
            or len(bytes(artifact.raw)) != artifact.size
            or sha256(bytes(artifact.raw)).hexdigest() != artifact.sha256
            or artifact.sha256 != event.artifact_sha256
        ):
            raise cases.CaseConflict("export_artifact_integrity")
        # Failed slots expose only ordinal/status. Every selected resource still
        # needs its export permission; every included byte must remain readable.
        records, files, outcomes = _read_selection(
            case, actor, common["provider"], job.selection, job.include_files, allow_missing=True
        )
        raw, manifest = archive(job=job, records=records, files=files, outcomes=outcomes)
        if raw != bytes(artifact.raw) or manifest != artifact.manifest:
            raise cases.CaseConflict("export_source_or_result_changed")
        key = cases._uuid(request_key)
        replay = job.events.filter(request_key=key).first()
        if replay and replay.action != "DOWNLOAD":
            raise cases.CaseConflict("export_idempotency_conflict")
        if not replay:
            _record(
                job,
                actor,
                common["provider"],
                action="DOWNLOAD",
                state=event.state,
                request_key=key,
                previous=event,
            )
        return {
            "raw": raw,
            "sha256": artifact.sha256,
            "filename": f"selected-export-{job.pk}.zip",
            "partial": event.state == "PARTIAL",
        }
