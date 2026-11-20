"""Authenticated transcript revisions and separately reviewed public media editions."""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from hashlib import sha256

from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.platform_recovery.integration import mutation_service

from .boundaries import Boundary, _permit, staff_boundary
from .boundaries import assert_projection_state as assert_projection_state
from .boundaries import assert_snapshot as assert_snapshot
from .boundaries import snapshot as snapshot
from .models import PublicMediaAction, PublicMediaEdition, RecordingTranscript, TranscriptAction

MAX_SEGMENTS = 6
TRANSCRIPT_ACTIONS = {"REVIEW", "APPROVE_MEANING", "WITHDRAW"}
MEDIA_ACTIONS = {"REVIEW", "RELEASE", "WITHDRAW"}


def _json(value):
    def default(item):
        if isinstance(item, uuid.UUID):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat(timespec="microseconds")
        raise TypeError

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=default
    )


def _digest(value):
    return sha256(_json(value).encode()).hexdigest()


def _body(row):
    return {
        field.attname: getattr(row, field.attname)
        for field in row._meta.concrete_fields
        if field.attname not in {"canonical_payload", "digest", "created_at"}
    }


def _seal(row):
    row.canonical_payload = _json(_body(row))
    row.digest = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    return row


def _verify(row):
    if (
        row.canonical_payload != _json(_body(row))
        or row.digest != sha256(row.canonical_payload.encode()).hexdigest()
    ):
        raise cases.CaseConflict("recording_history_invalid")


def _text(value, maximum, empty=False):
    if (
        type(value) is not str
        or len(value) > maximum
        or (not empty and not value.strip())
        or any(ord(c) < 32 and c not in "\n\r\t" for c in value)
    ):
        raise cases.CaseConflict("recording_text_invalid")
    return value


def _count(value, maximum=64):
    if type(value) is not int or not 0 <= value <= maximum:
        raise cases.CaseConflict("recording_expected_version_invalid")
    return value


def _record_fields(guard, actor, request_key, request_sha256):
    return dict(
        subject_id=actor.subject_id,
        provider_id=guard.provider.provider_id,
        auth_epoch=actor.auth_epoch,
        case_revision=guard.case.revision,
        evidence_version=guard.case.evidence_version,
        request_key=cases._uuid(request_key),
        request_sha256=request_sha256,
    )


def _resource(part, transcript=None, edition=None):
    return {
        "part_id": str(part.pk),
        "part_sha256": part.sha256,
        "transcript_id": str(transcript.pk) if transcript else "",
        "transcript_digest": transcript.digest if transcript else "",
        "edition_id": str(edition.pk) if edition else "",
        "edition_digest": edition.digest if edition else "",
    }


def _source(guard, actor, part_id):
    media._enabled()
    part = (
        AnswerPart.objects.select_related("manifest__answer__decision")
        .filter(pk=cases._uuid(part_id), manifest__answer__case=guard.case, kind="AUDIO")
        .first()
    )
    if part is None:
        raise cases.CaseConflict("recording_source_unavailable")
    answer = part.manifest.answer
    decision = media._current(guard.case, part.manifest)
    guard.actor(answer.subject_id, answer.auth_epoch, answer.provider_id)
    guard.actor(decision.subject_id, decision.auth_epoch, decision.provider_id)
    raw = guard.audio(actor, part)
    if (
        not media._metadata_valid(part)
        or len(raw) != part.size
        or sha256(raw).hexdigest() != part.sha256
    ):
        raise cases.CaseConflict("recording_source_invalid")
    duration = int(
        (Decimal(str(part.metadata["duration_seconds"])) * 1000).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    if not 1 <= duration <= 120000:
        raise cases.CaseConflict("recording_duration_invalid")
    pins = {
        "answer_id": str(answer.pk),
        "answer_revision": answer.revision,
        "answer_sha256": sha256(answer.text.encode()).hexdigest(),
        "decision_id": str(decision.pk),
        "evidence_version": answer.evidence_version,
        "manifest_sha256": part.manifest.sha256,
        "part_id": str(part.pk),
        "part_sha256": part.sha256,
        "size": part.size,
        "media_type": part.media_type,
        "metadata_sha256": _digest(part.metadata),
        "duration_ms": duration,
    }
    return part, pins, raw


def segments_for_text(text, rows, duration_ms):
    """Only explicit exact-text offsets and documented source times; never align by guess."""
    if type(rows) is not list or len(rows) > MAX_SEGMENTS:
        raise cases.CaseConflict("recording_segments_invalid")
    result, last_char, last_time = [], 0, 0
    for row in rows:
        if type(row) is not dict or set(row) != {"char_start", "char_end", "start_ms", "end_ms"}:
            raise cases.CaseConflict("recording_segments_invalid")
        if any(type(value) is not int for value in row.values()):
            raise cases.CaseConflict("recording_segments_invalid")
        a, b, start, end = (row[key] for key in ("char_start", "char_end", "start_ms", "end_ms"))
        if (
            not 0 <= last_char <= a < b <= len(text)
            or not 0 <= last_time <= start < end <= duration_ms
        ):
            raise cases.CaseConflict("recording_segments_invalid")
        if not text[a:b].strip():
            raise cases.CaseConflict("recording_segments_invalid")
        result.append({**row, "sha256": sha256(text[a:b].encode()).hexdigest()})
        last_char, last_time = b, end
    return result


def _transcript(guard, actor, transcript_id, *, reviewed=False):
    row = (
        RecordingTranscript.objects.select_related("part")
        .filter(pk=cases._uuid(transcript_id), case=guard.case)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("recording_transcript_unavailable")
    _verify(row)
    part, pins, raw = _source(guard, actor, row.part_id)
    if pins != row.source_pins or sha256(row.text.encode()).hexdigest() != row.text_sha256:
        raise cases.CaseConflict("recording_transcript_source_changed")
    expected_segments = segments_for_text(
        row.text,
        [
            {key: value for key, value in segment.items() if key != "sha256"}
            for segment in row.segments
        ],
        pins["duration_ms"],
    )
    if expected_segments != row.segments:
        raise cases.CaseConflict("recording_segments_invalid")
    guard.actor(row.subject_id, row.auth_epoch, row.provider_id)
    guard.permit(actor, "READ_TRANSCRIPT", _resource(part, row))
    actions = list(row.actions.order_by("sequence"))
    previous = row.digest
    for index, event in enumerate(actions, 1):
        _verify(event)
        if event.previous_digest != previous or event.sequence != index:
            raise cases.CaseConflict("recording_history_invalid")
        previous = event.digest
    if reviewed:
        needed = "APPROVE_MEANING" if row.change_kind == "MEANING_REVIEW" else "REVIEW"
        review = next((a for a in actions if a.action == needed), None)
        if review is None or any(a.action == "WITHDRAW" for a in actions):
            raise cases.CaseConflict("recording_review_required")
        reviewer = guard.actor(review.subject_id, review.auth_epoch, review.provider_id)
        guard.permit(
            reviewer,
            "REVIEW_MEANING" if needed == "APPROVE_MEANING" else "REVIEW_TRANSCRIPT",
            _resource(part, row),
        )
    return row, part, raw, actions


def _transcript_dto(row, actions):
    return {
        "id": str(row.pk),
        "number": row.number,
        "digest": row.digest,
        "part_id": str(row.part_id),
        "text": row.text,
        "segments": row.segments,
        "change_kind": row.change_kind,
        "note": row.note,
        "created_at": row.created_at,
        "subject_id": row.subject_id,
        "action_count": len(actions),
        "history": [_action_dto(a) for a in actions],
        "reviewed": bool(actions)
        and actions[0].action in {"REVIEW", "APPROVE_MEANING"}
        and not any(a.action == "WITHDRAW" for a in actions),
        "audio_url": f"/casework/staff/recording-transcripts/{row.pk}/audio/",
    }


def _action_dto(row):
    return {
        "action": row.action,
        "subject_id": row.subject_id,
        "note": row.note,
        "created_at": row.created_at,
    }


def _replay(model, guard, actor, request_key, request_digest):
    row = model.objects.filter(
        provider_id=guard.provider.provider_id,
        subject_id=actor.subject_id,
        request_key=cases._uuid(request_key),
    ).first()
    if row and row.request_sha256 != request_digest:
        raise cases.CaseConflict("recording_idempotency_conflict")
    if row:
        _verify(row)
    return row


@mutation_service
def save_transcript(
    *, part_id, text, segments, change_kind, note, expected_version, request_key, **common
):
    cases._mutation_versions(
        common.get("expected_revision"), common.get("expected_evidence_version")
    )
    _text(text, 10000)
    _text(note, 1000)
    _count(expected_version)
    if change_kind not in {"EDITORIAL", "MEANING_REVIEW"}:
        raise cases.CaseConflict("recording_change_kind_invalid")
    request_digest = _digest(
        [
            str(part_id),
            text,
            segments,
            change_kind,
            note,
            expected_version,
            common.get("expected_revision"),
            common.get("expected_evidence_version"),
        ]
    )
    with staff_boundary(**common) as (guard, actor):
        part, pins, _ = _source(guard, actor, part_id)
        guard.permit(actor, "EDIT_TRANSCRIPT", _resource(part))
        validated = segments_for_text(text, segments, pins["duration_ms"])
        replay = _replay(RecordingTranscript, guard, actor, request_key, request_digest)
        if replay:
            if replay.case_id != guard.case.pk:
                raise cases.CaseConflict("recording_idempotency_conflict")
            row, _, _, actions = _transcript(guard, actor, replay.pk)
            return _transcript_dto(row, actions)
        previous = RecordingTranscript.objects.filter(part=part).order_by("-number").first()
        if (previous.number if previous else 0) != expected_version or expected_version >= 64:
            raise cases.CaseConflict("recording_transcript_version_changed")
        guard.before_write()
        row = _seal(
            RecordingTranscript(
                case=guard.case,
                part=part,
                number=expected_version + 1,
                previous=previous,
                source_pins=pins,
                text=text,
                text_sha256=sha256(text.encode()).hexdigest(),
                segments=validated,
                change_kind=change_kind,
                note=note,
                **_record_fields(guard, actor, request_key, request_digest),
            )
        )
        guard.freeze_after_write()
        return _transcript_dto(row, [])


@mutation_service
def review_transcript(
    *, transcript_id, action, note, confirmed, expected_actions, request_key, **common
):
    cases._mutation_versions(
        common.get("expected_revision"), common.get("expected_evidence_version")
    )
    if action not in TRANSCRIPT_ACTIONS or confirmed is not True:
        raise cases.CaseConflict("recording_review_confirmation_required")
    _text(note, 1000)
    _count(expected_actions, 2)
    request_digest = _digest(
        [
            str(transcript_id),
            action,
            note,
            expected_actions,
            common.get("expected_revision"),
            common.get("expected_evidence_version"),
        ]
    )
    with staff_boundary(**common) as (guard, actor):
        row, part, _, actions = _transcript(guard, actor, transcript_id)
        permission = {
            "REVIEW": "REVIEW_TRANSCRIPT",
            "APPROVE_MEANING": "REVIEW_MEANING",
            "WITHDRAW": "WITHDRAW_TRANSCRIPT",
        }[action]
        guard.permit(actor, permission, _resource(part, row))
        replay = _replay(TranscriptAction, guard, actor, request_key, request_digest)
        if replay:
            if replay.transcript_id != row.pk:
                raise cases.CaseConflict("recording_idempotency_conflict")
            return _transcript_dto(row, actions)
        if len(actions) != expected_actions or any(a.action == "WITHDRAW" for a in actions):
            raise cases.CaseConflict("recording_review_state_changed")
        needed = "APPROVE_MEANING" if row.change_kind == "MEANING_REVIEW" else "REVIEW"
        if action != "WITHDRAW" and (
            action != needed
            or actions
            or (row.provider_id, row.subject_id) == (guard.provider.provider_id, actor.subject_id)
        ):
            raise cases.CaseConflict("recording_independent_review_required")
        guard.before_write()
        event = _seal(
            TranscriptAction(
                transcript=row,
                sequence=len(actions) + 1,
                previous_digest=actions[-1].digest if actions else row.digest,
                action=action,
                note=note,
                **_record_fields(guard, actor, request_key, request_digest),
            )
        )
        guard.freeze_after_write()
        return _transcript_dto(row, [*actions, event])


def _publication(guard, publication_id):
    publication._enabled()
    row = (
        PublicationEdition.objects.select_related("answer", "decision")
        .filter(pk=cases._uuid(publication_id), case=guard.case)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("recording_publication_unavailable")
    publication._approved(guard.case, row)
    publication._verify(row)
    actions = {a.action: a for a in row.actions.all()}
    latest = (
        PublicationEdition.objects.filter(case=guard.case, actions__action="APPROVE")
        .order_by("-number")
        .first()
    )
    from apps.library_preview.services import _independent

    if latest is None or latest.pk != row.pk or not _independent(row) or "WITHDRAW" in actions:
        raise cases.CaseConflict("recording_publication_unavailable")
    if row.citations != publication._citation_snapshot(row.answer):
        raise cases.CaseConflict("recording_publication_source_changed")
    end = publication._require_publication_sources(guard.case, row.citations)
    if end:
        guard.pin.deadlines.append(end)
    for event in (row, actions["REVIEW"], actions["APPROVE"]):
        guard.actor(event.subject_id, event.auth_epoch, event.provider_id)
    return row


def _edition(guard, actor, edition_id, *, released=False):
    row = PublicMediaEdition.objects.filter(pk=cases._uuid(edition_id), case=guard.case).first()
    if row is None:
        raise cases.CaseConflict("recording_media_unavailable")
    _verify(row)
    source = _publication(guard, row.publication_id)
    part, pins, raw = _source(guard, actor, row.part_id)
    if (
        pins != row.source_pins
        or source.answer_id != part.manifest.answer_id
        or row.publication_sha256 != source.content_sha256
    ):
        raise cases.CaseConflict("recording_media_source_changed")
    transcript = None
    if row.transcript_id:
        transcript, _, _, _ = _transcript(guard, actor, row.transcript_id, reviewed=True)
        if transcript.digest != row.transcript_digest or transcript.part_id != part.pk:
            raise cases.CaseConflict("recording_media_transcript_changed")
    guard.actor(row.subject_id, row.auth_epoch, row.provider_id)
    actions = list(row.actions.order_by("sequence"))
    previous = row.digest
    for index, event in enumerate(actions, 1):
        _verify(event)
        if event.sequence != index or event.previous_digest != previous:
            raise cases.CaseConflict("recording_history_invalid")
        previous = event.digest
    if released:
        by_action = {a.action: a for a in actions}
        if (
            set(by_action) != {"REVIEW", "RELEASE"}
            or by_action["RELEASE"].valid_until <= timezone.now()
        ):
            raise cases.CaseConflict("recording_public_release_required")
        for command, permission in (("REVIEW", "REVIEW_MEDIA"), ("RELEASE", "RELEASE_MEDIA")):
            event = by_action[command]
            recorded_actor = guard.actor(event.subject_id, event.auth_epoch, event.provider_id)
            guard.permit(recorded_actor, permission, _resource(part, transcript, row))
        release = by_action["RELEASE"]
        releaser = guard.actor(release.subject_id, release.auth_epoch, release.provider_id)
        guard.permit(releaser, "PUBLIC_AUDIO", _resource(part, transcript, row))
        if transcript:
            guard.permit(releaser, "PUBLIC_TRANSCRIPT", _resource(part, transcript, row))
        guard.audio(releaser, part)
        guard.pin.deadlines.append(release.valid_until)
    return row, part, raw, transcript, actions


def _edition_dto(row, actions):
    return {
        "id": str(row.pk),
        "number": row.number,
        "digest": row.digest,
        "publication_id": str(row.publication_id),
        "part_id": str(row.part_id),
        "transcript_id": str(row.transcript_id) if row.transcript_id else "",
        "label": row.label,
        "note": row.note,
        "action_count": len(actions),
        "history": [_action_dto(event) for event in actions],
        "created_at": row.created_at,
        "subject_id": row.subject_id,
        "public_url": f"/library-preview/publications/{row.publication_id}/recordings/",
        "released": bool(actions)
        and actions[-1].action == "RELEASE"
        and actions[-1].valid_until > timezone.now(),
    }


def _options(guard, actor, row, actions, *, media_edition=False):
    proposed = []
    current = (guard.provider.provider_id, actor.subject_id)
    if not actions and current != (row.provider_id, row.subject_id):
        proposed.append(
            "REVIEW" if media_edition or row.change_kind == "EDITORIAL" else "APPROVE_MEANING"
        )
    if (
        media_edition
        and len(actions) == 1
        and actions[0].action == "REVIEW"
        and current
        not in {(row.provider_id, row.subject_id), (actions[0].provider_id, actions[0].subject_id)}
    ):
        proposed.append("RELEASE")
    if not any(event.action == "WITHDRAW" for event in actions):
        proposed.append("WITHDRAW")
    resource = _resource(
        row.part, row.transcript if media_edition else row, row if media_edition else None
    )
    result = []
    for command in proposed:
        permission = (
            {"REVIEW": "REVIEW_MEDIA", "RELEASE": "RELEASE_MEDIA", "WITHDRAW": "WITHDRAW_MEDIA"}
            if media_edition
            else {
                "REVIEW": "REVIEW_TRANSCRIPT",
                "APPROVE_MEANING": "REVIEW_MEANING",
                "WITHDRAW": "WITHDRAW_TRANSCRIPT",
            }
        )[command]
        values = dict(
            provider_id=guard.provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=guard.case.public_ref,
            action=permission,
            resource=resource,
        )
        try:
            _permit(guard.pin.authority, values)
        except cases.CaseConflict as exc:
            if str(exc) == "recording_action_denied":
                continue
            raise
        guard.permissions.append(values)
        result.append(command)
    return result


@mutation_service
def prepare_media(
    *, publication_id, part_id, transcript_id, label, note, expected_version, request_key, **common
):
    cases._mutation_versions(
        common.get("expected_revision"), common.get("expected_evidence_version")
    )
    _text(label, 120)
    _text(note, 1000)
    _count(expected_version)
    request_digest = _digest(
        [
            str(publication_id),
            str(part_id),
            str(transcript_id or ""),
            label,
            note,
            expected_version,
            common.get("expected_revision"),
            common.get("expected_evidence_version"),
        ]
    )
    with staff_boundary(**common) as (guard, actor):
        source = _publication(guard, publication_id)
        part, pins, _ = _source(guard, actor, part_id)
        if source.answer_id != part.manifest.answer_id:
            raise cases.CaseConflict("recording_media_source_changed")
        transcript = None
        if transcript_id:
            transcript, _, _, _ = _transcript(guard, actor, transcript_id, reviewed=True)
            if transcript.part_id != part.pk:
                raise cases.CaseConflict("recording_media_transcript_changed")
        guard.permit(actor, "PREPARE_MEDIA", _resource(part, transcript))
        replay = _replay(PublicMediaEdition, guard, actor, request_key, request_digest)
        if replay:
            row, _, _, _, actions = _edition(guard, actor, replay.pk)
            return _edition_dto(row, actions)
        previous = (
            PublicMediaEdition.objects.filter(publication=source, part=part)
            .order_by("-number")
            .first()
        )
        if (previous.number if previous else 0) != expected_version or expected_version >= 64:
            raise cases.CaseConflict("recording_media_version_changed")
        guard.before_write()
        row = _seal(
            PublicMediaEdition(
                case=guard.case,
                publication=source,
                part=part,
                transcript=transcript,
                number=expected_version + 1,
                previous=previous,
                label=label,
                note=note,
                source_pins=pins,
                publication_sha256=source.content_sha256,
                transcript_digest=transcript.digest if transcript else "",
                **_record_fields(guard, actor, request_key, request_digest),
            )
        )
        guard.freeze_after_write()
        return _edition_dto(row, [])


@mutation_service
def review_media(
    *, edition_id, action, note, confirmed, expected_actions, request_key, minutes=0, **common
):
    cases._mutation_versions(
        common.get("expected_revision"), common.get("expected_evidence_version")
    )
    if action not in MEDIA_ACTIONS or confirmed is not True:
        raise cases.CaseConflict("recording_release_confirmation_required")
    _text(note, 1000)
    _count(expected_actions, 3)
    if type(minutes) is not int or not (
        1 <= minutes <= 60 if action == "RELEASE" else minutes == 0
    ):
        raise cases.CaseConflict("recording_release_expiry_invalid")
    request_digest = _digest(
        [
            str(edition_id),
            action,
            note,
            expected_actions,
            minutes,
            common.get("expected_revision"),
            common.get("expected_evidence_version"),
        ]
    )
    with staff_boundary(**common) as (guard, actor):
        row, part, _, transcript, actions = _edition(guard, actor, edition_id)
        permission = {
            "REVIEW": "REVIEW_MEDIA",
            "RELEASE": "RELEASE_MEDIA",
            "WITHDRAW": "WITHDRAW_MEDIA",
        }[action]
        guard.permit(actor, permission, _resource(part, transcript, row))
        replay = _replay(PublicMediaAction, guard, actor, request_key, request_digest)
        if replay:
            if replay.edition_id != row.pk:
                raise cases.CaseConflict("recording_idempotency_conflict")
            return _edition_dto(row, actions)
        if len(actions) != expected_actions or any(a.action == "WITHDRAW" for a in actions):
            raise cases.CaseConflict("recording_media_state_changed")
        if action == "REVIEW" and (
            actions
            or (row.provider_id, row.subject_id) == (guard.provider.provider_id, actor.subject_id)
        ):
            raise cases.CaseConflict("recording_independent_media_review_required")
        if action == "RELEASE":
            if (
                len(actions) != 1
                or actions[0].action != "REVIEW"
                or (guard.provider.provider_id, actor.subject_id)
                in {
                    (row.provider_id, row.subject_id),
                    (actions[0].provider_id, actions[0].subject_id),
                }
            ):
                raise cases.CaseConflict("recording_independent_release_required")
            reviewer = guard.actor(
                actions[0].subject_id, actions[0].auth_epoch, actions[0].provider_id
            )
            guard.permit(reviewer, "REVIEW_MEDIA", _resource(part, transcript, row))
            guard.permit(actor, "PUBLIC_AUDIO", _resource(part, transcript, row))
            if transcript:
                guard.permit(actor, "PUBLIC_TRANSCRIPT", _resource(part, transcript, row))
        guard.before_write()
        event = _seal(
            PublicMediaAction(
                edition=row,
                sequence=len(actions) + 1,
                previous_digest=actions[-1].digest if actions else row.digest,
                action=action,
                note=note,
                valid_until=timezone.now() + timedelta(minutes=minutes)
                if action == "RELEASE"
                else None,
                **_record_fields(guard, actor, request_key, request_digest),
            )
        )
        guard.freeze_after_write()
        return _edition_dto(row, [*actions, event])


@contextmanager
def desk_projection(**common):
    with staff_boundary(**common) as (guard, actor):
        rows, parts, editions = [], [], []
        for part in AnswerPart.objects.filter(
            manifest__answer_id=guard.case.approved_answer_id, kind="AUDIO"
        ).order_by("ordinal"):
            part, pins, _ = _source(guard, actor, part.pk)
            guard.permit(actor, "READ_TRANSCRIPT", _resource(part))
            all_rows = list(RecordingTranscript.objects.filter(part=part).order_by("number"))
            latest = all_rows[-1] if all_rows else None
            saved_segments = latest.segments if latest else []
            inputs = []
            for index in range(MAX_SEGMENTS):
                segment = saved_segments[index] if index < len(saved_segments) else None
                inputs.append(
                    {
                        "index": index,
                        "quote": latest.text[segment["char_start"] : segment["char_end"]]
                        if segment
                        else "",
                        "start_ms": segment["start_ms"] if segment else "",
                        "end_ms": segment["end_ms"] if segment else "",
                    }
                )
            parts.append(
                {
                    "id": str(part.pk),
                    "ordinal": part.ordinal,
                    "duration_ms": pins["duration_ms"],
                    "version": latest.number if latest else 0,
                    "text": latest.text if latest else "",
                    "segment_inputs": inputs,
                    "audio_url": f"/casework/staff/recording-parts/{part.pk}/audio/",
                }
            )
            for row in all_rows:
                row, _, _, actions = _transcript(guard, actor, row.pk)
                rows.append(
                    {
                        **_transcript_dto(row, actions),
                        "options": _options(guard, actor, row, actions),
                    }
                )
        publications = []
        source = (
            PublicationEdition.objects.filter(case=guard.case, actions__action="APPROVE")
            .order_by("-number")
            .first()
        )
        if source:
            source = _publication(guard, source.pk)
            publications.append({"id": str(source.pk), "title": source.title})
            for row in PublicMediaEdition.objects.filter(publication=source).order_by(
                "part_id", "number"
            ):
                # A withdrawn transcript does not erase its editorial audit trail.
                _verify(row)
                actions = list(row.actions.order_by("sequence"))
                for event in actions:
                    _verify(event)
                editions.append(
                    {
                        **_edition_dto(row, actions),
                        "options": _options(guard, actor, row, actions, media_edition=True),
                    }
                )
            for part in parts:
                part["media_version"] = max(
                    (e["number"] for e in editions if e["part_id"] == part["id"]), default=0
                )
        guard.before_write()
        yield {
            "case_ref": guard.case.public_ref,
            "revision": guard.case.revision,
            "evidence_version": guard.case.evidence_version,
            "parts": parts,
            "transcripts": rows,
            "editions": editions,
            "publications": publications,
        }


@contextmanager
def transcript_projection(*, transcript_id, **common):
    with staff_boundary(**common) as (guard, actor):
        row, part, raw, actions = _transcript(guard, actor, transcript_id)
        guard.before_write()
        yield {
            **_transcript_dto(row, actions),
            "raw": raw,
            "media_type": part.media_type,
            "filename": safe_filename(row.pk, part.media_type),
            "_snapshot": guard.pin,
        }


@contextmanager
def segment_projection(*, transcript_id, index, **common):
    with staff_boundary(**common) as (guard, actor):
        row, part, raw, _ = _transcript(guard, actor, transcript_id, reviewed=True)
        if type(index) is not int or not 0 <= index < len(row.segments):
            raise cases.CaseConflict("recording_segment_unavailable")
        segment = row.segments[index]
        pin = {
            "case_id": str(guard.case.pk),
            "transcript_id": str(row.pk),
            "transcript_digest": row.digest,
            "part_id": str(part.pk),
            "part_sha256": part.sha256,
            "segment_index": index,
            "segment_sha256": segment["sha256"],
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
        }
        guard.before_write()
        yield {
            "pin": pin,
            "text": row.text[segment["char_start"] : segment["char_end"]],
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
            "number": row.number,
            "case_ref": guard.case.public_ref,
            "audio_url": f"/casework/staff/recording-transcripts/{row.pk}/audio/#t={segment['start_ms'] / 1000:g},{segment['end_ms'] / 1000:g}",
            "snapshot": guard.pin,
        }


@contextmanager
def audio_projection(*, part_id, **common):
    with staff_boundary(**common) as (guard, actor):
        part, pins, raw = _source(guard, actor, part_id)
        guard.permit(actor, "READ_TRANSCRIPT", _resource(part))
        guard.before_write()
        yield {
            "raw": raw,
            "media_type": part.media_type,
            "filename": safe_filename(part.pk, part.media_type),
            "source_pins": pins,
        }


def safe_filename(public_id, media_type):
    extension = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(media_type)
    if extension is None:
        raise cases.CaseConflict("recording_media_type_invalid")
    return f"recording-{cases._uuid(public_id)}.{extension}"


@contextmanager
def search_projection(**common):
    """Canonical search consumes exact reviewed rows and retains _snapshot to its end.

    An unbound portable TranscriptLink is deliberately outside this contract.
    After this context exits the outer search must call assert_snapshot again,
    after its own last rights/identity callbacks and actual HTML rendering.
    """
    with staff_boundary(**common) as (guard, actor):
        rows = []
        for record in RecordingTranscript.objects.filter(case=guard.case).order_by(
            "part_id", "-number"
        ):
            # Historical reviewed revisions remain explicit; no unreviewed copy is indexed.
            if (
                not record.actions.filter(action__in=("REVIEW", "APPROVE_MEANING")).exists()
                or record.actions.filter(action="WITHDRAW").exists()
            ):
                continue
            candidate = Boundary(guard.case, guard.provider)
            try:
                row, part, _, _ = _transcript(candidate, actor, record.pk, reviewed=True)
                candidate.before_write()
            except cases.CaseConflict:
                # A preexisting denial is local to this optional source. The
                # outer pre-read epoch/state pin still rejects mutations made
                # by any failing candidate callback before a result can escape.
                continue
            guard.actors.update(candidate.actors)
            guard.permissions.extend(candidate.permissions)
            guard.media_permissions.extend(candidate.media_permissions)
            guard.pin.files.update(candidate.pin.files)
            guard.pin.deadlines.extend(candidate.pin.deadlines)
            for index, segment in enumerate(row.segments):
                pin = {
                    "case_id": str(guard.case.pk),
                    "transcript_id": str(row.pk),
                    "transcript_digest": row.digest,
                    "part_id": str(part.pk),
                    "part_sha256": part.sha256,
                    "segment_index": index,
                    "segment_sha256": segment["sha256"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                }
                rows.append(
                    {
                        "pin": pin,
                        "text": row.text[segment["char_start"] : segment["char_end"]],
                        "label": f"تفريغ مراجع · النسخة {row.number}",
                        "segment_url": f"/casework/staff/recording-transcripts/{row.pk}/segments/{index}/",
                    }
                )
        guard.before_write()
        yield {"rows": rows, "snapshot": guard.pin}
