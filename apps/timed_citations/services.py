"""Scoped human locators over exact canonical audio, never a new media store."""

import json
import os
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.data_privacy import integration as privacy
from apps.data_privacy.services import PrivacyDenied
from apps.platform_recovery.integration import mutation_service
from apps.private_media.validation import MediaValidationError, validate
from apps.research_workspace.rights import Resource, require
from apps.source_rights.services import _projection_deadline, projection_expiry_guard

from .models import TimedCitation, TimedCitationAction
from .rights import TimedMediaRights


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_TIMED_CITATIONS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("timed_citations_disabled")


def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _identity(case, actor, provider):
    fresh = cases._identity(provider, actor.subject_id, case)
    if (fresh.auth_epoch, fresh.role, fresh.case_keys) != (
        actor.auth_epoch,
        actor.role,
        actor.case_keys,
    ):
        raise cases.CaseConflict("timed_identity_changed")


def _rights(case, actor, provider, snapshot):
    resource = Resource(snapshot["kind"], snapshot["id"], snapshot["sha256"])
    policy = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    if not isinstance(policy, TimedMediaRights):
        raise cases.CaseConflict("timed_explicit_media_rights_required")
    from apps.casework.media_boundary import pin_media_deadline, pin_media_policy

    pin_media_policy(policy)
    # READ_MEDIA is not CITE. A configured policy must explicitly permit both.
    for action in ("READ_MEDIA", "CITE"):
        require(actor, provider, case, action, resource)
        try:
            deadline = policy.grant_deadline(
                provider_id=provider.provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                case_ref=case.public_ref,
                action=action,
                resource=resource,
            )
            if (
                not isinstance(deadline, datetime)
                or timezone.is_naive(deadline)
                or deadline <= timezone.now()
            ):
                raise ValueError
        except Exception as exc:
            raise cases.CaseConflict("timed_grant_expiry_required") from exc
        _projection_deadline(deadline)
        pin_media_deadline(deadline)
    # Deadline lookup is a configured authority call, not a cached grant. It
    # may observe a concurrent/serialized withdrawal after its first lookup.
    # Recheck both permissions after all deadline callbacks, before any caller
    # completes its final identity check or exposes source metadata/bytes.
    for action in ("READ_MEDIA", "CITE"):
        require(actor, provider, case, action, resource)


def _source(case, actor, provider, kind, identifier):
    """Internal adapter: caller already owns the authorized canonical case lock."""
    privacy.original("CASE", case.pk, provider=provider, actor=actor)
    identifier = cases._uuid(identifier)
    if kind == "ATTACHMENT":
        attachments._enabled()
        owner = (
            CaseAttachment.objects.filter(pk=identifier, case=case)
            .select_related("evidence", "event")
            .first()
        )
        if owner is None or owner.kind != "audio":
            raise cases.CaseConflict("timed_source_unavailable")
        version, recorded = owner.evidence.version, owner.validation_metadata
    elif kind == "ANSWER_MEDIA":
        media._enabled()
        owner = (
            AnswerPart.objects.filter(pk=identifier, manifest__answer__case=case)
            .select_related("manifest__answer")
            .first()
        )
        if owner is None or owner.kind != "AUDIO":
            raise cases.CaseConflict("timed_source_unavailable")
        privacy.original("ANSWER", owner.manifest.answer_id, provider=provider, actor=actor)
        version, recorded = owner.manifest.answer.revision, owner.metadata
    else:
        raise cases.CaseConflict("timed_source_kind_invalid")
    pin = {"kind": kind, "id": str(owner.pk), "sha256": owner.sha256}
    privacy.original(
        "ATTACHMENT" if kind == "ATTACHMENT" else "ANSWER_PART",
        owner.pk,
        provider=provider,
        actor=actor,
    )
    _rights(case, actor, provider, pin)
    if kind == "ATTACHMENT":
        raw = attachments._check(owner)
    else:
        cases._answer_citations(owner.manifest.answer)
        media._verified(owner.manifest)
        raw = media.raw_for_part(owner)
    try:
        verified = validate(raw, owner.filename, owner.media_type)
        duration = Decimal(str(verified.metadata["duration_seconds"])) * 1000
        if not duration.is_finite() or not 1 <= duration <= 120000:
            raise ValueError
        duration_ms = int(duration.to_integral_value(rounding=ROUND_FLOOR))
        if (
            verified.kind != "audio"
            or verified.sha256 != owner.sha256
            or verified.metadata != recorded
        ):
            raise ValueError
    except (MediaValidationError, KeyError, ValueError, InvalidOperation) as exc:
        raise cases.CaseConflict("timed_duration_unverified") from exc
    pin.update(
        version=version,
        duration_ms=duration_ms,
        metadata_sha256=_digest(recorded),
        filename=owner.filename,
        media_type=owner.media_type,
        size=owner.size,
    )
    _rights(case, actor, provider, pin)
    _identity(case, actor, provider)
    return pin, owner, raw


def _draft(case):
    answer = case.answers.filter(
        revision=case.answer_revision, evidence_version=case.evidence_version
    ).first()
    if (
        answer is None
        or case.stage != "UNDER_REVIEW"
        or case.approved_answer_id is not None
        or hasattr(answer, "decision")
    ):
        raise cases.CaseConflict("timed_current_unreviewed_answer_required")
    privacy.source("ANSWER", answer.pk)
    return answer


def _current(case, row):
    return (
        row.answer.revision == case.answer_revision
        and row.answer.evidence_version == case.evidence_version
    )


def _latest(row):
    if TimedCitation.objects.filter(series=row.series, number__gt=row.number).exists():
        raise cases.CaseConflict("timed_revision_superseded")


def _state(row):
    actions = set(row.actions.values_list("action", flat=True))
    return (
        "WITHDRAWN"
        if "WITHDRAW" in actions
        else "CONFIRMED"
        if "CONFIRM" in actions
        else "PROPOSED"
    )


def _validate(row, case, actor, provider):
    privacy.original("ANSWER", row.answer_id, provider=provider, actor=actor)
    if row.snapshot_sha256 != _digest(row.snapshot) or row.duration_ms != row.snapshot.get(
        "duration_ms"
    ):
        raise cases.CaseConflict("timed_snapshot_changed")
    pin, owner, raw = _source(case, actor, provider, row.snapshot["kind"], row.snapshot["id"])
    if pin != row.snapshot or str(owner.pk) != str(row.attachment_id or row.part_id):
        raise cases.CaseConflict("timed_source_changed")
    return raw


@mutation_service
def inspect_source(
    *, case_id, subject_id, provider, kind, source_id, synthetic_fixtures_only=False
):
    _enabled()
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        return _source(case, actor, provider, kind, source_id)[0]


@mutation_service
def propose(
    *,
    case_id,
    subject_id,
    provider,
    source_pin,
    start_ms,
    end_ms,
    reason,
    expected_revision,
    expected_evidence_version,
    replaces_id=None,
    synthetic_fixtures_only=False,
):
    _enabled()
    cases._mutation_versions(expected_revision, expected_evidence_version)
    cases._text(reason)
    if len(reason) > 1000 or type(start_ms) is not int or type(end_ms) is not int:
        raise cases.CaseConflict("timed_range_invalid")
    if type(source_pin) is not dict or set(source_pin) != {
        "kind",
        "id",
        "sha256",
        "version",
        "duration_ms",
        "metadata_sha256",
        "filename",
        "media_type",
        "size",
    }:
        raise cases.CaseConflict("timed_exact_source_pin_required")
    if any(type(source_pin[key]) is not int for key in ("version", "duration_ms", "size")):
        raise cases.CaseConflict("timed_exact_source_pin_required")
    with (
        cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
        projection_expiry_guard(),
    ):
        answer = _draft(case)
        pin, owner, _ = _source(case, actor, provider, source_pin["kind"], source_pin["id"])
        if source_pin != pin:
            raise cases.CaseConflict("timed_source_changed")
        if not 0 <= start_ms < end_ms <= pin["duration_ms"]:
            raise cases.CaseConflict("timed_range_invalid")
        previous = None
        if replaces_id is not None:
            previous = TimedCitation.objects.filter(pk=cases._uuid(replaces_id), case=case).first()
            if previous is None:
                raise cases.CaseConflict("timed_citation_unavailable")
            _latest(previous)
            if previous.number >= 64:
                raise cases.CaseConflict("timed_capacity")
        elif TimedCitation.objects.filter(case=case, number=1).count() >= 32:
            raise cases.CaseConflict("timed_capacity")
        _rights(case, actor, provider, pin)
        _identity(case, actor, provider)
        row = TimedCitation.objects.create(
            case=case,
            answer=answer,
            attachment=owner if pin["kind"] == "ATTACHMENT" else None,
            part=owner if pin["kind"] == "ANSWER_MEDIA" else None,
            previous=previous,
            number=previous.number + 1 if previous else 1,
            **({"series": previous.series} if previous else {}),
            snapshot=pin,
            snapshot_sha256=_digest(pin),
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=pin["duration_ms"],
            reason=reason,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return {"id": str(row.pk), "number": row.number, "state": "PROPOSED"}


@mutation_service
def act(
    *, case_id, subject_id, provider, citation_id, action, confirmed, synthetic_fixtures_only=False
):
    _enabled()
    if confirmed is not True or action not in {"CONFIRM", "WITHDRAW"}:
        raise cases.CaseConflict("timed_human_confirmation_required")
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        row = (
            TimedCitation.objects.filter(pk=cases._uuid(citation_id), case=case)
            .select_related("answer")
            .first()
        )
        if row is None:
            raise cases.CaseConflict("timed_citation_unavailable")
        _latest(row)
        state = _state(row)
        if state == "WITHDRAWN" or action == "CONFIRM" and state != "PROPOSED":
            raise cases.CaseConflict("timed_transition_invalid")
        if action == "CONFIRM":
            if row.answer_id != _draft(case).pk:
                raise cases.CaseConflict("timed_answer_changed")
            _validate(row, case, actor, provider)
        _identity(case, actor, provider)
        TimedCitationAction.objects.create(
            citation=row,
            action=action,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return {"id": str(row.pk), "state": _state(row)}


@mutation_service
def open_audio(
    *,
    case_id,
    subject_id,
    provider,
    citation_id,
    review=False,
    context_ms=0,
    synthetic_fixtures_only=False,
):
    _enabled()
    if (
        type(review) is not bool
        or type(context_ms) is not int
        or not 0 <= context_ms <= 5000
        or (context_ms and not review)
    ):
        raise cases.CaseConflict("timed_review_invalid")
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        row = (
            TimedCitation.objects.filter(pk=cases._uuid(citation_id), case=case)
            .select_related("answer")
            .first()
        )
        if row is None:
            raise cases.CaseConflict("timed_citation_unavailable")
        _latest(row)
        if not _current(case, row) or _state(row) not in (
            {"PROPOSED", "CONFIRMED"} if review else {"CONFIRMED"}
        ):
            raise cases.CaseConflict("timed_current_confirmation_required")
        if review and _draft(case).pk != row.answer_id:
            raise cases.CaseConflict("timed_answer_changed")
        raw = _validate(row, case, actor, provider)
        _rights(case, actor, provider, row.snapshot)
        _identity(case, actor, provider)
        return {
            "raw": raw,
            "media_type": row.snapshot["media_type"],
            "filename": row.snapshot["filename"],
            "start_ms": row.start_ms,
            "end_ms": row.end_ms,
            "duration_ms": row.duration_ms,
            "preview_start_ms": max(0, row.start_ms - context_ms),
            "preview_end_ms": min(row.duration_ms, row.end_ms + context_ms),
            "source_version": row.snapshot["version"],
            "source_sha256": row.snapshot["sha256"],
        }


@privacy.projected
@projection_expiry_guard()
def for_locked_answer(*, answer, actor, provider):
    """Integrator hook before canonical approval/use; no automatic relation cloning.

    Caller holds the authorized case lock. Missing/pending/withdrawn/superseded
    references cannot be used as current citations. This never grants approval.
    """
    _enabled()
    if not connection.in_atomic_block:
        raise cases.CaseConflict("timed_case_lock_required")
    case = answer.case
    output = []
    for row in TimedCitation.objects.filter(answer=answer).select_related("answer"):
        if TimedCitation.objects.filter(series=row.series, number__gt=row.number).exists():
            continue
        if not _current(case, row) or _state(row) != "CONFIRMED":
            raise cases.CaseConflict("timed_current_confirmation_required")
        _validate(row, case, actor, provider)
        output.append(
            {
                "id": str(row.pk),
                "source": row.snapshot,
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "number": row.number,
            }
        )
    # Final pass prevents a multi-row result outliving permissions checked earlier.
    for item in output:
        _rights(case, actor, provider, item["source"])
    _identity(case, actor, provider)
    return output


@mutation_service
def desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        sources = []
        owners = [
            ("ATTACHMENT", pk)
            for pk in CaseAttachment.objects.filter(case=case, kind="audio").values_list(
                "pk", flat=True
            )
        ]
        owners += [
            ("ANSWER_MEDIA", pk)
            for pk in AnswerPart.objects.filter(
                manifest__answer__case=case,
                manifest__answer__revision=case.answer_revision,
                kind="AUDIO",
            ).values_list("pk", flat=True)
        ]
        for kind, identifier in owners[:64]:
            try:
                sources.append(_source(case, actor, provider, kind, identifier)[0])
            except cases.CaseConflict:
                continue
        history = []
        seen = set()
        for row in (
            TimedCitation.objects.filter(case=case)
            .select_related("answer")
            .order_by("series", "-number")
        ):
            latest = row.series not in seen
            seen.add(row.series)
            entry = {
                "id": str(row.pk),
                "number": row.number,
                "state": _state(row),
                "current": _current(case, row),
                "latest": latest,
                "source": None,
                "reason": "",
                "start_ms": None,
                "end_ms": None,
            }
            try:
                _validate(row, case, actor, provider)
                entry.update(source=row.snapshot, start_ms=row.start_ms, end_ms=row.end_ms)
                # A correction reason may refer to the previous recording.
                if row.previous_id:
                    _validate(row.previous, case, actor, provider)
                entry["reason"] = row.reason
            except PrivacyDenied:
                continue
            except cases.CaseConflict:
                pass
            history.append(entry)
        for pin in sources:
            _rights(case, actor, provider, pin)
        for entry in history:
            if entry["source"] is not None:
                _rights(case, actor, provider, entry["source"])
        _identity(case, actor, provider)
        return {
            "public_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "sources": sources,
            "history": history,
            "answer_revision": case.answer_revision,
            "can_propose": case.stage == "UNDER_REVIEW" and not case.approved_answer_id,
        }
