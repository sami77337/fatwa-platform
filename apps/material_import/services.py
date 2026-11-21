"""Staged plans become usable canonical library versions only after independent review."""

import uuid
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service
from apps.upload_security import integration as scans
from apps.upload_security import services as scan_receipts

from . import formats, policy
from .models import (
    GroupResult,
    ImportBatch,
    ImportDecision,
    ImportEvent,
    ImportPlan,
    MappingRevision,
)

ZERO = "0" * 64
MAX_BATCHES = 32
STATE_LABELS = {
    "STAGED": "حُفظ الأصل؛ لم يُطبّق على المكتبة",
    "MAPPED": "حُفظ ربط الحقول؛ أعد المعاينة",
    "PLANNED": "معاينة فقط؛ تحتاج مراجعة مستقلة",
    "BLOCKED": "توجد أخطاء أو تعارضات مانعة",
    "APPROVED": "اعتمدت خطة الإدخال تقنيًا؛ لم تُنفّذ بعد",
    "REJECTED": "رُفضت الخطة مع حفظ أسباب المراجعة",
    "PARTIAL": "نُفّذت بعض المجموعات؛ بقيت مجموعات غير منفذة",
    "FAILED": "تعذرت المحاولة؛ لم تُنفّذ أي مجموعة",
    "APPLIED": "اكتمل النطاق المعتمد وطوبقت سجلاته",
    "CANCELLED": "أُلغي ما لم ينفذ؛ بقيت السجلات السابقة محفوظة",
    "EXPIRED": "انتهت صلاحية الدفعة؛ سجلها ونتائجها محفوظة",
    "STALE": "تغيرت نسخة مستهدفة أو القضية؛ يلزم فحص جديد",
}


def _library():
    from apps.research_library import services

    return services


def _parse(batch):
    raw = bytes(batch.raw)
    if sha256(raw).hexdigest() != batch.raw_sha256:
        raise cases.CaseConflict("import_source_integrity")
    scans.require_bytes(raw)
    parsed = formats.parse(raw, batch.filename)
    for file in parsed.files.values():
        scan_receipts.require(file.sha256, file.size)
    return parsed


def _pins(case, base):
    if (
        base.get("expected_revision", case.revision) != case.revision
        or base.get("expected_evidence_version", case.evidence_version) != case.evidence_version
    ):
        raise cases.CaseConflict("import_case_changed")


def _actor(actor, provider):
    return dict(
        provider_id=provider.provider_id, subject_id=actor.subject_id, auth_epoch=actor.auth_epoch
    )


def _event_data(event):
    return {
        "batch_id": str(event.batch_id),
        "sequence": event.sequence,
        "request_key": str(event.request_key),
        "action": event.action,
        "detail": event.detail,
        "provider_id": event.provider_id,
        "subject_id": event.subject_id,
        "auth_epoch": event.auth_epoch,
        "previous_digest": event.previous_digest,
    }


def _events(batch):
    events = list(batch.events.order_by("sequence")[:129])
    previous = ZERO
    for number, event in enumerate(events, 1):
        if (
            event.sequence != number
            or event.previous_digest != previous
            or event.digest != formats.digest(_event_data(event))
        ):
            raise cases.CaseConflict("import_history_invalid")
        previous = event.digest
    if not events or len(events) > 128:
        raise cases.CaseConflict("import_history_invalid")
    return events


def _record(batch, actor, provider, action, request_key, detail):
    previous = batch.events.order_by("-sequence").first()
    number = previous.sequence + 1 if previous else 1
    # Always retain room to cancel; rendering/expiry never consumes history.
    if number > (128 if action == "CANCEL" else 127):
        raise cases.CaseConflict("import_history_capacity")
    event = ImportEvent(
        batch=batch,
        sequence=number,
        request_key=cases._uuid(request_key),
        action=action,
        detail=detail,
        previous_digest=previous.digest if previous else ZERO,
        **_actor(actor, provider),
    )
    event.digest = formats.digest(_event_data(event))
    event.save(force_insert=True)
    return event


def _get(case, actor, provider, batch_id, *, action="VIEW"):
    batch = ImportBatch.objects.filter(pk=cases._uuid(batch_id), case=case).first()
    if batch is None:
        raise cases.CaseConflict("import_batch_unavailable")
    policy.permit(case, actor, provider, action, batch.namespace)
    _events(batch)
    _parse(batch)
    return batch


def _open(batch, expected_sequence=None, *, allow_started=False):
    events = _events(batch)
    if expected_sequence is not None and (
        type(expected_sequence) is not int or events[-1].sequence != expected_sequence
    ):
        raise cases.CaseConflict("import_stale_command")
    if batch.expires_at <= timezone.now():
        raise cases.CaseConflict("import_expired")
    if any(event.action == "CANCEL" for event in events):
        raise cases.CaseConflict("import_cancelled")
    if not allow_started and GroupResult.objects.filter(plan__batch=batch).exists():
        raise cases.CaseConflict("import_already_started")
    return events[-1]


def _replay(batch, request_key, action, command, actor, provider):
    event = batch.events.filter(request_key=cases._uuid(request_key)).first()
    if event is None:
        return False
    if (
        event.action != action
        or event.detail.get("command") != formats.digest(command)
        or event.subject_id != actor.subject_id
        or event.provider_id != provider.provider_id
    ):
        raise cases.CaseConflict("import_idempotency_conflict")
    return True


def _mapping(batch):
    row = batch.mappings.order_by("-number").first()
    if row is None:
        return None
    if row.digest != formats.digest({"mapping": row.mapping, "resolutions": row.resolutions}):
        raise cases.CaseConflict("import_mapping_integrity")
    formats.validate_mapping(row.mapping, _parse(batch))
    if type(row.resolutions) is not dict or len(row.resolutions) > 20:
        raise cases.CaseConflict("import_mapping_integrity")
    for external_id, resolution in row.resolutions.items():
        formats.identifier(external_id)
        if (
            type(resolution) is not dict
            or set(resolution) != {"choice", "target"}
            or resolution["choice"] not in {"NEW_VERSION", "SKIP"}
            or type(resolution["target"]) is not dict
            or set(resolution["target"]) != {"item_id", "version_id", "number", "digest"}
        ):
            raise cases.CaseConflict("import_mapping_integrity")
    return row


def _new_mapping(batch, actor, provider, mapping, resolutions):
    old = _mapping(batch)
    number = old.number + 1 if old else 1
    if number > 32:
        raise cases.CaseConflict("import_mapping_capacity")
    return MappingRevision.objects.create(
        batch=batch,
        number=number,
        mapping=mapping,
        resolutions=resolutions,
        digest=formats.digest({"mapping": mapping, "resolutions": resolutions}),
        **_actor(actor, provider),
    )


def _plan_digest(plan):
    return formats.digest(
        {
            "batch_id": str(plan.batch_id),
            "raw": plan.batch.raw_sha256,
            "namespace": plan.batch.namespace,
            "mapping_id": str(plan.mapping_id),
            "mapping_digest": plan.mapping.digest,
            "number": plan.number,
            "case_revision": plan.case_revision,
            "evidence_version": plan.evidence_version,
            "expires_at": plan.expires_at.isoformat(),
            "report": plan.report,
        }
    )


def _latest_plan(batch):
    plan = batch.plans.select_related("mapping", "batch").order_by("-number").first()
    if plan is not None and plan.digest != _plan_digest(plan):
        raise cases.CaseConflict("import_plan_integrity")
    return plan


def _target(value):
    if value is None:
        return None
    return {key: value[key] for key in ("item_id", "version_id", "number", "digest")}


def _file_identity(value):
    return None if value is None else {key: value[key] for key in ("sha256", "size", "media_type")}


def _current(batch, external_id, base):
    return _record_dto(
        _library().current_material(**base, namespace=batch.namespace, external_id=external_id)
    )


def _record_dto(value):
    """Persist the declared import contract, never extra permissions or decisions."""
    if value is None:
        return None
    result = {key: value[key] for key in ("item_id", "version_id", "number", "digest", "payload")}
    result["file"] = (
        {key: value["file"][key] for key in ("sha256", "size", "media_type", "filename")}
        if value["file"]
        else None
    )
    return result


def _build_report(batch, mapping, base):
    parsed = _parse(batch)
    results = []
    used_files = set()
    for ordinal, original in enumerate(parsed.rows, 1):
        row = dict(
            ordinal=ordinal,
            external_id="",
            group=f"row-{ordinal}",
            action="BLOCK",
            reason="",
            payload={},
            file=None,
            target=None,
            changed_fields=[],
            preserved_fields=[],
        )
        try:
            external_id, group, member, payload = formats.mapped(
                original,
                mapping.mapping,
                provenance=batch.provenance,
                rights_basis=batch.rights_basis,
            )
            row.update(external_id=external_id, group=group)
            current = _current(batch, external_id, base)
            row["target"] = _target(current)
            if member:
                if member not in parsed.files:
                    raise formats.ImportInputError("referenced_file_missing")
                used_files.add(member)
            source_file = parsed.files.get(member)
            if current and current["payload"]["kind"] != payload["kind"]:
                raise formats.ImportInputError("material_kind_conflict")
            if current is not None:
                for field, value in payload.items():
                    if value == "" and current["payload"].get(field):
                        payload[field] = current["payload"][field]
                        row["preserved_fields"].append(field)
                if not mapping.mapping["language"]:
                    payload["language"] = current["payload"]["language"]
            media = _library().validate_material(
                payload,
                file_bytes=source_file.raw if source_file else b"",
                filename=source_file.filename if source_file else "",
                media_type=source_file.media_type if source_file else "",
            )
            wanted_file = (
                {
                    "sha256": media.sha256,
                    "size": media.size,
                    "media_type": media.media_type,
                    "filename": media.filename,
                }
                if media
                else (current["file"] if current else None)
            )
            if current and _file_identity(current["file"]) == _file_identity(wanted_file):
                # A renamed identical physical file is not a new logical edition.
                wanted_file = current["file"]
            row.update(
                payload=payload,
                file={**wanted_file, "path": member} if wanted_file else None,
                target=_target(current),
                action="ADD",
                reason="new_material",
            )
            if current is not None:
                row["changed_fields"] = [
                    key for key, value in payload.items() if current["payload"].get(key) != value
                ]
                if _file_identity(wanted_file) != _file_identity(current["file"]):
                    row["changed_fields"].append("file")
                if not row["changed_fields"]:
                    row.update(action="SKIP", reason="identical_material")
                else:
                    resolution = mapping.resolutions.get(external_id)
                    if resolution and resolution.get("target") == _target(current):
                        row.update(
                            action="UPDATE" if resolution["choice"] == "NEW_VERSION" else "SKIP",
                            reason="explicit_new_version"
                            if resolution["choice"] == "NEW_VERSION"
                            else "preserve_existing",
                        )
                    else:
                        row.update(action="BLOCK", reason="human_conflict")
        except formats.ImportInputError as exc:
            row.update(action="BLOCK", reason=str(exc))
        except cases.CaseConflict as exc:
            if str(exc) in {
                "library_payload_invalid",
                "library_text_bound",
                "library_file_invalid",
                "library_file_kind_mismatch",
                "invalid_case_text",
            }:
                row.update(action="BLOCK", reason="material_or_file_invalid")
                results.append(row)
                continue
            # Authorization is not a row validation warning; no partial projection.
            raise
        except ValueError:
            row.update(action="BLOCK", reason="material_or_file_invalid")
        results.append(row)
    counts = Counter(row["external_id"] for row in results if row["external_id"])
    for row in results:
        if counts[row["external_id"]] > 1:
            row.update(action="BLOCK", reason="duplicate_external_id")
    unreferenced = sorted(set(parsed.files) - used_files)
    return {
        "schema": formats.SCHEMA,
        "rows": results,
        "unreferenced_files": unreferenced,
        "counts": dict(Counter(row["action"] for row in results)),
        "ready": not unreferenced and all(row["action"] != "BLOCK" for row in results),
    }


def _group_rows(plan):
    result = {}
    for row in plan.report["rows"]:
        result.setdefault(row["group"], []).append(row)
    return result


def _results(plan):
    results = list(plan.groups.order_by("group_key")[:21])
    if len(results) > 20:
        raise cases.CaseConflict("import_group_integrity")
    for group in results:
        if group.digest != formats.digest(group.outcomes) or group.group_key not in _group_rows(
            plan
        ):
            raise cases.CaseConflict("import_group_integrity")
        expected = _group_rows(plan)[group.group_key]
        if type(group.outcomes) is not list or len(group.outcomes) != len(expected):
            raise cases.CaseConflict("import_group_integrity")
        for row, outcome in zip(expected, group.outcomes, strict=True):
            if (
                type(outcome) is not dict
                or set(outcome) != {"external_id", "action", "result"}
                or outcome["external_id"] != row["external_id"]
                or outcome["action"] != row["action"]
            ):
                raise cases.CaseConflict("import_group_integrity")
            _verify_written(row, outcome["result"])
    return results


def _check_targets(plan, base):
    completed = {
        row["external_id"]: row["result"] for group in _results(plan) for row in group.outcomes
    }
    for row in plan.report["rows"]:
        if not row["external_id"]:
            continue
        expected = (
            _target(completed[row["external_id"]])
            if row["external_id"] in completed
            else row["target"]
        )
        if _target(_current(plan.batch, row["external_id"], base)) != expected:
            raise cases.CaseConflict("import_target_changed")


def _valid_plan(batch, case, base, *, approved=False):
    plan = _latest_plan(batch)
    mapping = _mapping(batch)
    if (
        plan is None
        or mapping is None
        or plan.mapping_id != mapping.pk
        or plan.case_revision != case.revision
        or plan.evidence_version != case.evidence_version
        or plan.expires_at <= timezone.now()
    ):
        raise cases.CaseConflict("import_plan_stale")
    _check_targets(plan, base)
    if approved:
        decision = ImportDecision.objects.filter(plan=plan, verdict="APPROVE").first()
        if decision is None or not plan.report["ready"]:
            raise cases.CaseConflict("import_approval_required")
    return plan


def _projection(batch, case, actor, provider, base):
    parsed = _parse(batch)
    events = _events(batch)
    mapping = _mapping(batch)
    plan = _latest_plan(batch)
    groups = _results(plan) if plan else []
    decision = ImportDecision.objects.filter(plan=plan).first() if plan else None
    stale = False
    if plan and mapping and plan.mapping_id == mapping.pk:
        try:
            _valid_plan(batch, case, base)
        except cases.CaseConflict as exc:
            if str(exc) not in {"import_target_changed", "import_plan_stale"}:
                raise
            stale = True
    state = "STAGED"
    if mapping:
        state = "MAPPED"
    if plan and mapping and plan.mapping_id == mapping.pk:
        state = "PLANNED" if plan.report["ready"] else "BLOCKED"
        if decision:
            state = "APPROVED" if decision.verdict == "APPROVE" else "REJECTED"
        if events[-1].action == "FAIL":
            state = "FAILED"
        if groups:
            state = "APPLIED" if len(groups) == len(_group_rows(plan)) else "PARTIAL"
        if stale:
            state = "STALE"
    if batch.expires_at <= timezone.now():
        state = "EXPIRED"
    if any(event.action == "CANCEL" for event in events):
        state = "CANCELLED"
    current_report = (
        deepcopy(plan.report)
        if plan and mapping and plan.mapping_id == mapping.pk and not stale
        else None
    )
    if current_report:
        for row in current_report["rows"]:
            current = _current(batch, row["external_id"], base) if row["external_id"] else None
            row["current"] = current
    policy.permit(case, actor, provider, "VIEW", batch.namespace)
    return {
        "id": str(batch.pk),
        "case_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "namespace": batch.namespace,
        "filename": batch.filename,
        "raw_sha256": batch.raw_sha256,
        "format": batch.format,
        "provenance": batch.provenance,
        "rights_basis": batch.rights_basis,
        "expires_at": batch.expires_at,
        "sequence": events[-1].sequence,
        "state": state,
        "state_label": STATE_LABELS[state],
        "columns": list(parsed.columns),
        "row_count": len(parsed.rows),
        "mapping": mapping.mapping if mapping else formats.default_mapping(parsed),
        "mapping_number": mapping.number if mapping else 0,
        "plan": {
            "id": str(plan.pk),
            "number": plan.number,
            "digest": plan.digest,
            "report": current_report,
            "author": plan.subject_id,
            "expires_at": plan.expires_at,
        }
        if plan
        else None,
        "decision": {
            "verdict": decision.verdict,
            "reviewer": decision.subject_id,
            "note": decision.note,
            "verification_note": decision.verification_note,
        }
        if decision
        else None,
        "completed_groups": len(groups),
        "total_groups": len(_group_rows(plan)) if plan else 0,
        "results": [
            {"group": group.group_key, "outcomes": group.outcomes if not stale else []}
            for group in groups
        ],
        "history": [
            {
                "sequence": e.sequence,
                "action": e.action,
                "subject": e.subject_id,
                "created_at": e.created_at,
                "code": e.detail.get("code", ""),
            }
            for e in events
        ],
        "can_change": state
        in {"STAGED", "MAPPED", "PLANNED", "BLOCKED", "APPROVED", "REJECTED", "STALE"}
        and not groups,
        "can_approve": state == "PLANNED"
        and actor.subject_id not in {batch.subject_id, mapping.subject_id, plan.subject_id},
        "can_review": state in {"PLANNED", "BLOCKED"}
        and actor.subject_id not in {batch.subject_id, mapping.subject_id, plan.subject_id},
        "can_apply": state in {"APPROVED", "PARTIAL", "FAILED"},
        "can_cancel": state not in {"CANCELLED", "EXPIRED", "APPLIED"},
    }


@mutation_service
def list_batches(**base):
    with policy.boundary(**base) as (case, actor):
        rows = []
        for batch in ImportBatch.objects.filter(case=case).order_by("-created_at", "id")[
            :MAX_BATCHES
        ]:
            policy.permit(case, actor, base["provider"], "VIEW", batch.namespace)
            rows.append(
                {
                    "id": str(batch.pk),
                    "namespace": batch.namespace,
                    "filename": batch.filename,
                    "sha256": batch.raw_sha256,
                    "created_at": batch.created_at,
                }
            )
        return {
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "batches": rows,
        }


@mutation_service
def read_batch(*, batch_id, **base):
    with policy.boundary(**base) as (case, actor):
        batch = _get(case, actor, base["provider"], batch_id)
        return _projection(batch, case, actor, base["provider"], base)


@mutation_service
def stage(*, raw, filename, namespace, provenance, rights_basis, request_key, **base):
    parsed = scans.import_source(raw=raw, filename=filename, namespace=namespace, **base)
    formats.identifier(namespace)
    if parsed.origin and parsed.origin["namespace"] != namespace:
        raise formats.ImportInputError("roundtrip_namespace_mismatch")
    formats.text(provenance, 1000)
    formats.text(rights_basis, 1000)
    raw_sha = sha256(raw).hexdigest()
    with (
        scan_receipts.boundary(),
        policy.boundary(**base, action="STAGE", namespace=namespace) as (case, actor),
    ):
        scans.require_bytes(raw)
        for file in parsed.files.values():
            scan_receipts.require(file.sha256, file.size)
        _pins(case, base)
        existing = ImportBatch.objects.filter(
            case=case, namespace=namespace, raw_sha256=raw_sha
        ).first()
        if existing:
            if (
                existing.provenance != provenance
                or existing.rights_basis != rights_basis
                or existing.format != parsed.format
            ):
                raise cases.CaseConflict("import_source_receipt_conflict")
            return _projection(existing, case, actor, base["provider"], base)
        if ImportBatch.objects.filter(case=case).count() >= MAX_BATCHES:
            raise cases.CaseConflict("import_batch_capacity")
        if ImportBatch.objects.filter(
            case=case,
            provider_id=base["provider"].provider_id,
            subject_id=actor.subject_id,
            request_key=cases._uuid(request_key),
        ).exists():
            raise cases.CaseConflict("import_idempotency_conflict")
        ttl = getattr(settings, "FATWA_MATERIAL_IMPORT_TTL_SECONDS", 1800)
        if type(ttl) is not int or not 60 <= ttl <= 3600:
            raise cases.CaseConflict("import_ttl_invalid")
        batch = ImportBatch.objects.create(
            case=case,
            request_key=cases._uuid(request_key),
            namespace=namespace,
            filename=filename,
            format=parsed.format,
            raw=raw,
            raw_sha256=raw_sha,
            provenance=provenance,
            rights_basis=rights_basis,
            case_revision=case.revision,
            evidence_version=case.evidence_version,
            expires_at=timezone.now() + timedelta(seconds=ttl),
            **_actor(actor, base["provider"]),
        )
        _record(batch, actor, base["provider"], "STAGE", request_key, {"raw_sha256": raw_sha})
        return _projection(batch, case, actor, base["provider"], base)


@mutation_service
def configure(*, batch_id, mapping, expected_sequence, request_key, **base):
    with policy.boundary(**base, action="MAP") as (case, actor):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="MAP")
        formats.validate_mapping(mapping, _parse(batch))
        command = {"mapping": mapping, "sequence": expected_sequence}
        if not _replay(batch, request_key, "MAP", command, actor, base["provider"]):
            _open(batch, expected_sequence)
            row = _new_mapping(batch, actor, base["provider"], mapping, {})
            _record(
                batch,
                actor,
                base["provider"],
                "MAP",
                request_key,
                {"mapping": str(row.pk), "command": formats.digest(command)},
            )
        return _projection(batch, case, actor, base["provider"], base)


@mutation_service
def prepare_plan(*, batch_id, expected_sequence, request_key, **base):
    with policy.boundary(**base, action="PLAN") as (case, actor):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="PLAN")
        command = {"sequence": expected_sequence}
        if not _replay(batch, request_key, "PLAN", command, actor, base["provider"]):
            _open(batch, expected_sequence)
            mapping = _mapping(batch)
            if mapping is None:
                raise cases.CaseConflict("import_mapping_required")
            previous = _latest_plan(batch)
            number = previous.number + 1 if previous else 1
            if number > 32:
                raise cases.CaseConflict("import_plan_capacity")
            report = _build_report(batch, mapping, base)
            plan = ImportPlan(
                batch=batch,
                mapping=mapping,
                number=number,
                report=report,
                case_revision=case.revision,
                evidence_version=case.evidence_version,
                expires_at=batch.expires_at,
                **_actor(actor, base["provider"]),
            )
            plan.digest = _plan_digest(plan)
            plan.save(force_insert=True)
            _check_targets(plan, base)
            _record(
                batch,
                actor,
                base["provider"],
                "PLAN",
                request_key,
                {"plan": str(plan.pk), "command": formats.digest(command)},
            )
        return _projection(batch, case, actor, base["provider"], base)


@mutation_service
def resolve_conflict(
    *, batch_id, external_id, choice, expected_target, expected_sequence, request_key, **base
):
    formats.identifier(external_id)
    if choice not in {"NEW_VERSION", "SKIP"}:
        raise cases.CaseConflict("import_resolution_invalid")
    with policy.boundary(**base, action="MAP") as (case, actor):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="MAP")
        command = {
            "external_id": external_id,
            "choice": choice,
            "target": expected_target,
            "sequence": expected_sequence,
        }
        if not _replay(batch, request_key, "RESOLVE", command, actor, base["provider"]):
            _open(batch, expected_sequence)
            plan = _valid_plan(batch, case, base)
            row = next(
                (row for row in plan.report["rows"] if row["external_id"] == external_id), None
            )
            if row is None or row["reason"] != "human_conflict" or row["target"] != expected_target:
                raise cases.CaseConflict("import_conflict_changed")
            mapping = _mapping(batch)
            resolutions = {
                **mapping.resolutions,
                external_id: {"choice": choice, "target": expected_target},
            }
            revised = _new_mapping(batch, actor, base["provider"], mapping.mapping, resolutions)
            _record(
                batch,
                actor,
                base["provider"],
                "RESOLVE",
                request_key,
                {"mapping": str(revised.pk), "command": formats.digest(command)},
            )
        return _projection(batch, case, actor, base["provider"], base)


@mutation_service
def decide(
    *, batch_id, plan_id, verdict, note, verification_note, expected_sequence, request_key, **base
):
    if verdict not in {"APPROVE", "REJECT"}:
        raise cases.CaseConflict("import_decision_invalid")
    formats.text(note, 2000)
    formats.text(verification_note, 2000)
    with policy.boundary(**base, action="REVIEW") as (case, actor):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="REVIEW")
        command = {
            "plan_id": str(plan_id),
            "verdict": verdict,
            "note": note,
            "verification_note": verification_note,
            "sequence": expected_sequence,
        }
        if not _replay(batch, request_key, verdict, command, actor, base["provider"]):
            _open(batch, expected_sequence)
            plan = _valid_plan(batch, case, base)
            if str(plan.pk) != str(plan_id) or ImportDecision.objects.filter(plan=plan).exists():
                raise cases.CaseConflict("import_decision_stale")
            if (actor.subject_id, base["provider"].provider_id) in {
                (batch.subject_id, batch.provider_id),
                (plan.subject_id, plan.provider_id),
                (plan.mapping.subject_id, plan.mapping.provider_id),
            }:
                raise cases.CaseConflict("import_independent_reviewer_required")
            if verdict == "APPROVE" and not plan.report["ready"]:
                raise cases.CaseConflict("import_blocked_plan")
            ImportDecision.objects.create(
                plan=plan,
                verdict=verdict,
                note=note,
                verification_note=verification_note,
                **_actor(actor, base["provider"]),
            )
            _record(
                batch,
                actor,
                base["provider"],
                verdict,
                request_key,
                {"plan": str(plan.pk), "command": formats.digest(command)},
            )
            _check_targets(plan, base)
        return _projection(batch, case, actor, base["provider"], base)


def _verify_written(row, result):
    if row["action"] == "SKIP":
        if _target(result) != row["target"]:
            raise cases.CaseConflict("import_reconciliation_failed")
        return
    if (
        result is None
        or result["payload"] != row["payload"]
        or _file_identity(result["file"]) != _file_identity(row["file"])
        or result["number"] != (row["target"]["number"] + 1 if row["target"] else 1)
    ):
        raise cases.CaseConflict("import_reconciliation_failed")


@mutation_service
def _group_files(*, batch_id, plan_id, group_key, **base):
    """Close the authorized readonly preflight before acquiring storage locks."""
    with policy.boundary(**base, action="APPLY") as (case, actor):
        batch = _get(case, actor, base["provider"], batch_id, action="APPLY")
        _open(batch, allow_started=True)
        plan = _valid_plan(batch, case, base, approved=True)
        if str(plan.pk) != plan_id:
            raise cases.CaseConflict("import_plan_stale")
        source = _parse(batch)
        return [
            source.files[row["file"]["path"]].raw
            for row in _group_rows(plan)[group_key]
            if row["action"] != "SKIP" and row["file"] and row["file"]["path"]
        ]


@mutation_service
def _apply_group(*, batch_id, plan_id, group_key, request_key, command_sequence, **base):
    raw_files = _group_files(batch_id=batch_id, plan_id=plan_id, group_key=group_key, **base)
    with (
        _library().material_bindings(raw_files),
        scan_receipts.boundary(),
        policy.boundary(**base, action="APPLY", allow_library_writes=True) as (case, actor),
    ):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="APPLY")
        _open(batch, allow_started=True)
        plan = _valid_plan(batch, case, base, approved=True)
        if str(plan.pk) != plan_id:
            raise cases.CaseConflict("import_plan_stale")
        existing = GroupResult.objects.filter(plan=plan, group_key=group_key).first()
        if existing:
            return
        rows = _group_rows(plan)[group_key]
        source = _parse(batch)
        outcomes = []
        for row in rows:
            current = _current(batch, row["external_id"], base)
            if _target(current) != row["target"]:
                raise cases.CaseConflict("import_target_changed")
            result = current
            if row["action"] != "SKIP":
                source_file = source.files.get(row["file"]["path"]) if row["file"] else None
                write_base = {
                    **base,
                    "expected_revision": plan.case_revision,
                    "expected_evidence_version": plan.evidence_version,
                }
                result = _record_dto(
                    _library().write_material(
                        **write_base,
                        namespace=batch.namespace,
                        external_id=row["external_id"],
                        payload=row["payload"],
                        file_bytes=source_file.raw if source_file else b"",
                        filename=source_file.filename if source_file else "",
                        media_type=source_file.media_type if source_file else "",
                        expected_version=row["target"]["number"] if row["target"] else 0,
                        request_key=uuid.uuid5(plan.pk, "material:" + row["external_id"]),
                    )
                )
                policy.record_material(case.pk, batch.namespace, row["external_id"], result)
            _verify_written(row, result)
            outcomes.append(
                {"external_id": row["external_id"], "action": row["action"], "result": result}
            )
        GroupResult.objects.create(
            plan=plan,
            group_key=group_key,
            outcomes=outcomes,
            digest=formats.digest(outcomes),
            **_actor(actor, base["provider"]),
        )
        _record(
            batch,
            actor,
            base["provider"],
            "APPLY",
            uuid.uuid5(cases._uuid(request_key), group_key),
            {
                "plan": plan_id,
                "group": group_key,
                "count": len(outcomes),
                "attempt": str(request_key),
                "command_sequence": command_sequence,
            },
        )
        _check_targets(plan, base)


@mutation_service
def _failure(*, batch_id, plan_id, group_key, request_key, command_sequence, **base):
    with policy.boundary(**base, action="APPLY") as (case, actor):
        batch = _get(case, actor, base["provider"], batch_id, action="APPLY")
        key = uuid.uuid5(cases._uuid(request_key), "failure:" + group_key)
        if not batch.events.filter(request_key=key).exists():
            _record(
                batch,
                actor,
                base["provider"],
                "FAIL",
                key,
                {
                    "plan": plan_id,
                    "group": group_key,
                    "code": "group_not_applied",
                    "attempt": str(request_key),
                    "command_sequence": command_sequence,
                },
            )


@mutation_service
def apply_batch(*, batch_id, expected_sequence, request_key, **base):
    # The admission guard is held, but there is deliberately no outer database
    # transaction across all groups. Each group either commits its canonical
    # versions + receipt together, or rolls back together. Prior groups survive.
    with policy.boundary(**base, action="APPLY") as (case, actor):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="APPLY")
        attempts = list(batch.events.filter(detail__attempt=str(request_key)))
        if attempts and any(
            e.subject_id != actor.subject_id
            or e.provider_id != base["provider"].provider_id
            or e.detail.get("command_sequence") != expected_sequence
            for e in attempts
        ):
            raise cases.CaseConflict("import_idempotency_conflict")
        _open(batch, None if attempts else expected_sequence, allow_started=True)
        plan = _valid_plan(batch, case, base, approved=True)
        groups = list(_group_rows(plan))
        completed = {group.group_key for group in _results(plan)}
        if _events(batch)[-1].sequence + len(set(groups) - completed) + 1 > 127:
            raise cases.CaseConflict("import_history_capacity")
        plan_id = str(plan.pk)
    for group_key in groups:
        if group_key in completed:
            continue
        try:
            _apply_group(
                batch_id=batch_id,
                plan_id=plan_id,
                group_key=group_key,
                request_key=request_key,
                command_sequence=expected_sequence,
                **base,
            )
        except (cases.CaseConflict, DatabaseError, ValueError):
            # No exception text or provider details enters the receipt. Access
            # withdrawal also blocks recording/reading a failure, fail-closed.
            _failure(
                batch_id=batch_id,
                plan_id=plan_id,
                group_key=group_key,
                request_key=request_key,
                command_sequence=expected_sequence,
                **base,
            )
            return read_batch(batch_id=batch_id, **base)
    return read_batch(batch_id=batch_id, **base)


@mutation_service
def cancel(*, batch_id, expected_sequence, request_key, **base):
    with policy.boundary(**base, action="CANCEL") as (case, actor):
        _pins(case, base)
        batch = _get(case, actor, base["provider"], batch_id, action="CANCEL")
        command = {"sequence": expected_sequence}
        if not _replay(batch, request_key, "CANCEL", command, actor, base["provider"]):
            _open(batch, expected_sequence, allow_started=True)
            plan = _latest_plan(batch)
            if plan and len(_results(plan)) == len(_group_rows(plan)):
                raise cases.CaseConflict("import_already_applied")
            _record(
                batch,
                actor,
                base["provider"],
                "CANCEL",
                request_key,
                {"command": formats.digest(command)},
            )
        return _projection(batch, case, actor, base["provider"], base)
