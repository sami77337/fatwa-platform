"""Independent, source-preserving destination histories; never an external sender."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta

from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_queue.services import _canonical
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview.services import _independent
from apps.platform_recovery.integration import mutation_service
from apps.research_library import services as library

from . import profiles
from .boundary import scope
from .models import DestinationEvent, DestinationRecord, DestinationVersion
from .signatures import SignedDestinationOutcome

LABELS = {
    "SELECTED": "محاكاة: نسخة مختارة لم تُراجع بعد",
    "REVIEW": "محاكاة: تمت المراجعة المستقلة",
    "APPROVE": "محاكاة: تم الاعتماد المستقل",
    "PREPARE": "محاكاة: خطة جاهزة، لم تُسجل نتيجة",
    "ACCEPTED": "محاكاة: قُبل الطلب ولم يثبت نشره",
    "SIMULATED_PUBLISHED": "محاكاة: نتيجة نشر ناجحة موقعة، ليست نشرًا فعليًا",
    "FAILED": "محاكاة: فشلت هذه النسخة في هذه الوجهة",
    "WITHDRAW": "محاكاة: سُحبت هذه النسخة من هذه الوجهة",
    "UNAVAILABLE": "محاكاة: النسخة غير متاحة تحت الصلاحيات أو المصادر الحالية",
}
HUMAN = ("REVIEW", "APPROVE", "PREPARE", "WITHDRAW")
PROVIDER = ("ACCEPTED", "SIMULATED_PUBLISHED", "FAILED")


def selection(source):
    return f"{source.pk}|{source.content_sha256}"


def _selected(value):
    if type(value) is not str or len(value) != 101 or value[36] != "|":
        raise cases.CaseConflict("destination_exact_source_required")
    identifier, digest = value.split("|")
    cases._uuid(identifier)
    if len(digest) != 64 or set(digest) - set("abcdef0123456789"):
        raise cases.CaseConflict("destination_exact_source_required")
    return identifier, digest


def source_pin(row):
    actions = {a.action: a for a in row.actions.all()}
    return {
        "id": str(row.pk),
        "sha256": row.content_sha256,
        "number": row.number,
        "case_id": str(row.case_id),
        "answer_id": str(row.answer_id),
        "answer_sha256": row.answer.text_sha256,
        "decision_id": str(row.decision_id),
        "evidence_version": row.evidence_version,
        "review_id": actions["REVIEW"].pk,
        "approval_id": actions["APPROVE"].pk,
    }


def source_current(guard, row):
    if row.case_id != guard.case_id:
        raise cases.CaseConflict("destination_source_case_mismatch")
    publication._verify(row)
    answer, decision = publication._approved(guard.case, row)
    if (
        not _independent(row)
        or row.actions.filter(action="WITHDRAW").exists()
        or row.citations != publication._citation_snapshot(answer)
    ):
        raise cases.CaseConflict("destination_source_unavailable")
    # Each destination selects its exact independently approved edition. A later
    # edition for another destination does not replace this one implicitly.
    actions = {a.action: a for a in row.actions.all()}
    for recorded in (answer, decision, row, actions["REVIEW"], actions["APPROVE"]):
        actor = guard.actor(guard.directory, recorded.subject_id, recorded)
        if recorded is actions["APPROVE"]:
            publication._authority(actor, guard.directory, guard.case, "APPROVE")
    deadline = publication._require_publication_sources(guard.case, row.citations)
    if deadline is not None:
        guard.deadlines.append(deadline)
    guard.sources[str(row.pk)] = row
    return source_pin(row)


def _public_copy(source):
    return dict(
        title=source.title, category=source.category, body=source.body, citations=source.citations
    )


def _profile(destination, source):
    configured = profiles.configured().get(destination)
    if (
        configured is None
        or len(source.title) + len(source.category) + len(source.body) > configured["max_chars"]
    ):
        raise cases.CaseConflict("destination_capability_unavailable")
    return configured


def _plan(row, profile, pins):
    return {
        "schema": "fatwa.destination-publication-plan.v1",
        "mode": "SYNTHETIC_ONLY",
        "record_id": str(row.record_id),
        "version_id": str(row.pk),
        "version": row.number,
        "destination": row.record.destination,
        "profile": profile,
        "source": pins,
        "public_copy": _public_copy(row.source),
        "external_publication_verified": False,
    }


def _verified(row):
    library._verify(row)
    publication._verify(row.source)
    try:
        profile = json.loads(row.profile_payload)
        plan = json.loads(row.plan_payload)
    except (ValueError, TypeError) as exc:
        raise cases.CaseConflict("destination_integrity_failed") from exc
    if (
        profiles.fingerprint(profile) != row.profile_sha256
        or profiles.fingerprint(plan) != row.plan_sha256
        or row.source_pins != source_pin(row.source)
        or plan != _plan(row, profile, row.source_pins)
        or row.source.case_id != row.record.case_id
    ):
        raise cases.CaseConflict("destination_integrity_failed")
    events = list(row.events.order_by("sequence"))
    previous = row.digest
    for number, event in enumerate(events, 1):
        library._verify(event)
        if (
            event.sequence != number
            or event.previous_digest != previous
            or event.plan_sha256 != row.plan_sha256
        ):
            raise cases.CaseConflict("destination_history_invalid")
        previous = event.digest
    return events


def _matches(event, row, preparation):
    return (
        event.record_id == str(row.record_id)
        and event.version_id == str(row.pk)
        and event.version_sha256 == row.digest
        and event.preparation_id == str(preparation.pk)
        and event.preparation_sha256 == preparation.digest
        and event.destination == row.record.destination
        and event.profile_sha256 == row.profile_sha256
        and event.plan_sha256 == row.plan_sha256
        and event.source_id == str(row.source_id)
        and event.source_sha256 == row.source.content_sha256
    )


def _current(guard, row, events):
    pins = source_current(guard, row.source)
    profile = _profile(row.record.destination, row.source)
    if pins != row.source_pins or profiles.fingerprint(profile) != row.profile_sha256:
        raise cases.CaseConflict("destination_current_profile_or_source_changed")
    actor = guard.actor(guard.directory, row.subject_id, row)
    guard.permit(
        guard.directory,
        actor,
        row.record.destination,
        "SELECT",
        row.source_id,
        row.source.content_sha256,
    )
    preparation = next((e for e in events if e.action == "PREPARE"), None)
    for item in events:
        actor = guard.actor(guard.directory, item.subject_id, item)
        action = "OBSERVE" if item.action in PROVIDER else item.action
        guard.permit(guard.directory, actor, row.record.destination, action, row.pk, row.digest)
        if item.action in PROVIDER:
            try:
                event = SignedDestinationOutcome(**item.provider_envelope)
            except (ValueError, TypeError) as exc:
                raise cases.CaseConflict("destination_saved_signature_invalid") from exc
            reported = "SIMULATED_PUBLISHED" if event.reported == "PUBLISHED" else event.reported
            if (
                preparation is None
                or not _matches(event, row, preparation)
                or item.action != reported
                or str(item.provider_event_id) != event.event_id
                or guard.verifier.verify(event, at=item.created_at) is not True
            ):
                raise cases.CaseConflict("destination_saved_signature_invalid")


def _base(guard, actor, request_key, note, confirmed, expected_revision, expected_evidence_version):
    cases._versions(guard.case, expected_revision, expected_evidence_version)
    cases._text(note)
    if confirmed is not True or len(note) > 1000:
        raise cases.CaseConflict("destination_explicit_confirmation_required")
    return dict(
        case_revision=guard.case.revision,
        evidence_version=guard.case.evidence_version,
        request_key=cases._uuid(request_key),
        provider_id=guard.provider.provider_id,
        subject_id=actor.subject_id,
        auth_epoch=actor.auth_epoch,
        note=note,
    )


def _request(audit, values):
    return profiles.fingerprint({**audit, "request_key": str(audit["request_key"]), **values})


def _replay(old, digest, audit):
    if (
        old.request_sha256 != digest
        or old.provider_id != audit["provider_id"]
        or old.subject_id != audit["subject_id"]
        or old.auth_epoch != audit["auth_epoch"]
    ):
        raise cases.CaseConflict("destination_request_key_conflict")


@mutation_service
def select(
    *,
    destination,
    source_selection,
    expected_version,
    request_key,
    note,
    confirmed,
    expected_revision,
    expected_evidence_version,
    **base,
):
    with scope(**base) as (guard, actor):
        return select_locked(
            guard,
            actor,
            destination=destination,
            source_selection=source_selection,
            expected_version=expected_version,
            request_key=request_key,
            note=note,
            confirmed=confirmed,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )


def select_locked(guard, actor, *, destination, source_selection, expected_version, **audit_values):
    audit = _base(guard, actor, **audit_values)
    if type(expected_version) is not int or not 0 <= expected_version < 64:
        raise cases.CaseConflict("destination_version_bound")
    identifier, digest = _selected(source_selection)
    source = (
        PublicationEdition.objects.select_related("answer", "decision")
        .filter(pk=identifier, case=guard.case)
        .first()
    )
    if source is None or source.content_sha256 != digest:
        raise cases.CaseConflict("destination_exact_source_required")
    profile = _profile(destination, source)
    pins = source_current(guard, source)
    guard.permit(guard.provider, actor, destination, "SELECT", source.pk, source.content_sha256)
    request_sha = _request(
        audit,
        dict(
            destination=destination,
            source_selection=source_selection,
            expected_version=expected_version,
            profile=profile,
        ),
    )
    old = (
        DestinationVersion.objects.select_related("record", "source__answer", "source__decision")
        .filter(request_key=audit["request_key"])
        .first()
    )
    if old is not None:
        _replay(old, request_sha, audit)
        if old.record.case_id != guard.case_id:
            raise cases.CaseConflict("destination_request_key_conflict")
        _current(guard, old, _verified(old))
        return old
    if DestinationEvent.objects.filter(request_key=audit["request_key"]).exists():
        raise cases.CaseConflict("destination_request_key_conflict")
    record = DestinationRecord.objects.filter(case=guard.case, destination=destination).first()
    prior = record.versions.order_by("-number").first() if record else None
    if (prior.number if prior else 0) != expected_version:
        raise cases.CaseConflict("destination_version_changed")
    guard.before_write()
    if record is None:
        record = DestinationRecord.objects.create(case=guard.case, destination=destination)
        guard.written()
    row = DestinationVersion(
        **audit,
        request_sha256=request_sha,
        record=record,
        number=expected_version + 1,
        previous_digest=prior.digest if prior else "0" * 64,
        source=source,
        source_pins=pins,
        profile_payload=_canonical(profile).decode(),
        profile_sha256=profiles.fingerprint(profile),
    )
    plan = _plan(row, profile, pins)
    row.plan_payload, row.plan_sha256 = _canonical(plan).decode(), profiles.fingerprint(plan)
    library._seal(row)
    guard.written()
    return row


def _row(guard, identifier):
    row = (
        DestinationVersion.objects.select_related("record", "source__answer", "source__decision")
        .filter(pk=cases._uuid(identifier), record__case=guard.case)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("destination_version_unavailable")
    return row


def _independent_actor(row, events, actor, provider, command):
    participants = {(row.provider_id, row.subject_id)}
    if command in ("APPROVE", "PREPARE"):
        participants.update((e.provider_id, e.subject_id) for e in events if e.action == "REVIEW")
        participants.add((row.source.decision.provider_id, row.source.decision.subject_id))
    if (
        command in ("REVIEW", "APPROVE", "PREPARE")
        and (provider.provider_id, actor.subject_id) in participants
    ):
        raise cases.CaseConflict("destination_independent_actor_required")


def _transition(row, events, command):
    state = events[-1].action if events else "SELECTED"
    if state == "WITHDRAW":
        raise cases.CaseConflict("destination_already_withdrawn")
    if command != "WITHDRAW" and row.record.versions.order_by("-number").first().pk != row.pk:
        raise cases.CaseConflict("destination_candidate_changed")
    allowed = {
        "REVIEW": {"SELECTED"},
        "APPROVE": {"REVIEW"},
        "PREPARE": {"APPROVE"},
        "ACCEPTED": {"PREPARE"},
        "SIMULATED_PUBLISHED": {"PREPARE", "ACCEPTED"},
        "FAILED": {"PREPARE", "ACCEPTED"},
        "WITHDRAW": {"SELECTED", "REVIEW", "APPROVE", "PREPARE", *PROVIDER},
    }
    if command not in allowed or state not in allowed[command]:
        raise cases.CaseConflict("destination_transition_invalid")


@mutation_service
def decide(
    *,
    version_id,
    command,
    expected_events,
    request_key,
    note,
    confirmed,
    expected_revision,
    expected_evidence_version,
    **base,
):
    with scope(**base) as (guard, actor):
        return decide_locked(
            guard,
            actor,
            version_id=version_id,
            command=command,
            expected_events=expected_events,
            request_key=request_key,
            note=note,
            confirmed=confirmed,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )


def decide_locked(guard, actor, *, version_id, command, expected_events, **audit_values):
    if command not in HUMAN:
        raise cases.CaseConflict("destination_human_command_invalid")
    audit = _base(guard, actor, **audit_values)
    row = _row(guard, version_id)
    events = _verified(row)
    deadline = guard.permit(
        guard.provider, actor, row.record.destination, command, row.pk, row.digest
    )
    if command != "WITHDRAW":
        _current(guard, row, events)
    request_sha = _request(
        audit, dict(version_id=str(row.pk), command=command, expected_events=expected_events)
    )
    old = DestinationEvent.objects.filter(request_key=audit["request_key"]).first()
    if old:
        _replay(old, request_sha, audit)
        return row
    if DestinationVersion.objects.filter(request_key=audit["request_key"]).exists():
        raise cases.CaseConflict("destination_request_key_conflict")
    if type(expected_events) is not int or expected_events != len(events):
        raise cases.CaseConflict("destination_events_changed")
    _transition(row, events, command)
    _independent_actor(row, events, actor, guard.provider, command)
    guard.before_write()
    until = (
        min([deadline, *guard.deadlines, timezone.now() + timedelta(minutes=15)])
        if command == "PREPARE"
        else None
    )
    library._seal(
        DestinationEvent(
            **audit,
            request_sha256=request_sha,
            version=row,
            sequence=len(events) + 1,
            previous_digest=events[-1].digest if events else row.digest,
            action=command,
            plan_sha256=row.plan_sha256,
            valid_until=until,
        )
    )
    guard.written()
    return row


@mutation_service
def observe(
    *,
    version_id,
    envelope,
    expected_events,
    request_key,
    note,
    confirmed,
    expected_revision,
    expected_evidence_version,
    **base,
):
    with scope(**base) as (guard, actor):
        return observe_locked(
            guard,
            actor,
            version_id=version_id,
            envelope=envelope,
            expected_events=expected_events,
            request_key=request_key,
            note=note,
            confirmed=confirmed,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )


def observe_locked(guard, actor, *, version_id, envelope, expected_events, **audit_values):
    audit = _base(guard, actor, **audit_values)
    if type(envelope) is not dict:
        raise cases.CaseConflict("destination_signed_outcome_required")
    try:
        event = SignedDestinationOutcome(**envelope)
    except (TypeError, ValueError) as exc:
        raise cases.CaseConflict("destination_signed_outcome_required") from exc
    row = _row(guard, version_id)
    events = _verified(row)
    _current(guard, row, events)
    guard.permit(guard.provider, actor, row.record.destination, "OBSERVE", row.pk, row.digest)
    preparation = next((e for e in events if e.action == "PREPARE"), None)
    if preparation is None or not _matches(event, row, preparation):
        raise cases.CaseConflict("destination_prepared_plan_mismatch")
    request_sha = _request(
        audit, dict(version_id=str(row.pk), envelope=envelope, expected_events=expected_events)
    )
    old = DestinationEvent.objects.filter(provider_event_id=cases._uuid(event.event_id)).first()
    by_request = DestinationEvent.objects.filter(request_key=audit["request_key"]).first()
    if old is not None or by_request is not None:
        if old is None or by_request is None or old.pk != by_request.pk:
            raise cases.CaseConflict("destination_request_key_conflict")
        _replay(old, request_sha, audit)
        return row
    if DestinationVersion.objects.filter(request_key=audit["request_key"]).exists():
        raise cases.CaseConflict("destination_request_key_conflict")
    if type(expected_events) is not int or expected_events != len(events):
        raise cases.CaseConflict("destination_events_changed")
    if preparation.valid_until <= timezone.now() or guard.verifier.verify(event) is not True:
        raise cases.CaseConflict("destination_signature_not_verified")
    from apps.delivery_queue.signed_provider_receipts import _utc

    if _utc(event.issued_at) < preparation.created_at - timedelta(seconds=30):
        raise cases.CaseConflict("destination_outcome_predates_preparation")
    command = "SIMULATED_PUBLISHED" if event.reported == "PUBLISHED" else event.reported
    _transition(row, events, command)
    guard.before_write()
    if guard.verifier.verify(event) is not True:
        raise cases.CaseConflict("destination_signature_not_verified")
    guard.pure()
    library._seal(
        DestinationEvent(
            **audit,
            request_sha256=request_sha,
            version=row,
            sequence=len(events) + 1,
            previous_digest=events[-1].digest,
            action=command,
            plan_sha256=row.plan_sha256,
            provider_event_id=event.event_id,
            provider_envelope=asdict(event),
        )
    )
    guard.written()
    return row


def row_dto(guard, actor, row):
    events = _verified(row)
    state = events[-1].action if events else "SELECTED"
    available = state != "WITHDRAW"
    if available:
        try:
            _current(guard, row, events)
            guard.permit(guard.provider, actor, row.record.destination, "READ", row.pk, row.digest)
        except cases.CaseConflict:
            available = False
    options = []
    for command in HUMAN:
        try:
            _transition(row, events, command)
            _independent_actor(row, events, actor, guard.provider, command)
            if command != "WITHDRAW" and not available:
                continue
            if guard.permit(
                guard.provider,
                actor,
                row.record.destination,
                command,
                row.pk,
                row.digest,
                required=False,
            ):
                options.append({"command": command, "label": LABELS[command]})
        except cases.CaseConflict:
            continue
    can_observe = (
        available
        and state in ("PREPARE", "ACCEPTED")
        and bool(
            guard.permit(
                guard.provider,
                actor,
                row.record.destination,
                "OBSERVE",
                row.pk,
                row.digest,
                required=False,
            )
        )
    )
    return {
        "id": str(row.pk),
        "record_id": str(row.record_id),
        "number": row.number,
        "digest": row.digest,
        "destination": row.record.destination,
        "source_id": str(row.source_id),
        "source_sha256": row.source.content_sha256,
        "source_number": row.source.number,
        "profile_sha256": row.profile_sha256,
        "plan_sha256": row.plan_sha256,
        "plan_payload": row.plan_payload if available else "",
        "state": state if available or state == "WITHDRAW" else "UNAVAILABLE",
        "state_label": LABELS[state if available or state == "WITHDRAW" else "UNAVAILABLE"],
        "available": available,
        "copy": _public_copy(row.source) if available else None,
        "event_count": len(events),
        "options": options,
        "can_observe": can_observe,
        "history": [
            {
                "action": e.action,
                "label": LABELS[e.action],
                "note": e.note,
                "actor": e.subject_id,
                "created_at": e.created_at,
                "digest": e.digest,
            }
            for e in events
        ],
        "external_publication_verified": False,
    }


def desk_locked(guard, actor):
    sources = []
    for source in (
        PublicationEdition.objects.select_related("answer", "decision")
        .filter(case=guard.case)
        .order_by("-number")[:64]
    ):
        try:
            source_current(guard, source)
        except cases.CaseConflict:
            continue
        sources.append(
            {"selection": selection(source), "number": source.number, **_public_copy(source)}
        )
    records = []
    for destination, profile in profiles.configured().items():
        record = DestinationRecord.objects.filter(case=guard.case, destination=destination).first()
        versions = (
            list(
                record.versions.select_related(
                    "record", "source__answer", "source__decision"
                ).order_by("-number")
            )
            if record
            else []
        )
        rows = [row_dto(guard, actor, row) for row in versions]
        published = next(
            (row for row in versions if row.events.filter(action="SIMULATED_PUBLISHED").exists()),
            None,
        )
        current = next((row for row in rows if published and row["id"] == str(published.pk)), None)
        if current is not None and current["state"] != "SIMULATED_PUBLISHED":
            current = None
        choices = []
        for source in sources:
            identifier, digest = _selected(source["selection"])
            if len(source["title"]) + len(source["category"]) + len(source["body"]) <= profile[
                "max_chars"
            ] and guard.permit(
                guard.provider, actor, destination, "SELECT", identifier, digest, required=False
            ):
                choices.append(source)
        records.append(
            {
                "destination": destination,
                "label": profiles.LABELS[destination],
                "id": str(record.pk) if record else "",
                "expected_version": versions[0].number if versions else 0,
                "versions": rows,
                "choices": choices,
                "current_published": current,
                "profile_sha256": profiles.fingerprint(profile),
                "profile_revision": profile["revision"],
            }
        )
    return dict(
        case_ref=guard.case.public_ref,
        revision=guard.case.revision,
        evidence_version=guard.case.evidence_version,
        records=records,
        external_publication_verified=False,
    )


@contextmanager
def desk_projection(**base):
    with scope(**base) as (guard, actor):
        yield desk_locked(guard, actor)
