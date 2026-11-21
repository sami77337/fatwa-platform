"""Reviewed exact attribution and lesson/series releases, without source grants."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.library_preview import services as preview
from apps.mufti_review.identity import resolve_identity
from apps.platform_recovery.integration import mutation_context, mutation_service
from apps.research_library import services as library
from apps.research_library.models import LibraryVersion
from apps.scholarly_links.models import SeriesVersion

from . import sources
from .authority import TeachingAuthority
from .models import TeachingAction, TeachingItem, TeachingVersion

KINDS = {
    "SCHOLAR_MATERIAL": "نسبة مادة عامة إلى عالم",
    "LESSON": "محتوى درس منشور",
    "SERIES": "سلسلة دروس منشورة",
}
COMMANDS = ("REVIEW", "APPROVE", "RELEASE", "WITHDRAW")
LABELS = {
    "DRAFT": "مسودة",
    "REVIEW": "مراجعة مستقلة",
    "APPROVE": "اعتماد مستقل",
    "RELEASE": "إتاحة محددة",
    "WITHDRAW": "سحب الإتاحة",
}
_CURRENT = ContextVar("public_teaching_boundary", default=None)


def enabled(*, public=False):
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLIC_TEACHING_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("teaching_disabled")
    if public and getattr(settings, "FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED", False) is not True:
        raise cases.CaseConflict("teaching_public_disabled")


def policy():
    enabled()
    authority = getattr(settings, "FATWA_PUBLIC_TEACHING_AUTHORITY", None)
    if not isinstance(authority, TeachingAuthority):
        raise cases.CaseConflict("teaching_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("teaching_authority_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise cases.CaseConflict("teaching_authority_snapshot_required")
    return authority, epoch


def history():
    return tuple(
        list(model.objects.order_by("pk").values())
        for model in (TeachingItem, TeachingVersion, TeachingAction)
    )


def _text(value, maximum, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > maximum:
        raise cases.CaseConflict("teaching_text_bound")
    return value


def _zero(value):
    if type(value) is not int or not 0 <= value < 65:
        raise cases.CaseConflict("teaching_version_bound")
    return value


def selection(row):
    return f"{row.pk}|{row.digest if hasattr(row, 'digest') else row.sha256}"


def _selection(value):
    if type(value) is not str or len(value) != 101 or value[36] != "|":
        raise cases.CaseConflict("teaching_exact_selection_required")
    identifier, digest = value.split("|")
    cases._uuid(identifier)
    if len(digest) != 64 or set(digest) - set("abcdef0123456789"):
        raise cases.CaseConflict("teaching_exact_selection_required")
    return identifier, digest


class Guard:
    def __init__(self, source, policy_pin, directory, directory_pin, rows):
        self.source = source
        self.authority, self.epoch = policy_pin
        self.directory, self.directory_pin = directory, directory_pin
        self.rows = rows
        self.permissions, self.identities, self.deadlines = [], {}, []
        self.provider_pins = {}
        self.read_pins = []
        self.public = False

    def actor(self, provider, subject, case_id, *, expected_epoch=None, expected_provider=None):
        if id(provider) not in self.provider_pins:
            self.provider_pins[id(provider)] = (provider, library.identity_snapshot(provider))
        case = self.source.locked.get(cases._uuid(case_id))
        if case is None:
            raise cases.CaseConflict("teaching_case_unavailable")
        actor = cases._identity(provider, subject, case)
        if (expected_epoch is not None and actor.auth_epoch != expected_epoch) or (
            expected_provider is not None and provider.provider_id != expected_provider
        ):
            raise cases.CaseConflict("teaching_recorded_actor_changed")
        key = (id(provider), subject, str(case.pk))
        old = self.identities.get(key)
        if old is not None and library._actor(old[1]) != library._actor(actor):
            raise cases.CaseConflict("teaching_identity_changed")
        self.identities[key] = (provider, actor, case)
        self.deadlines.append(actor.valid_until)
        return actor, case

    def _call(self, values, *, required=True):
        try:
            allowed = self.authority.permits(**values)
            deadline = self.authority.grant_deadline(**values) if allowed is True else None
        except Exception as exc:
            raise cases.CaseConflict("teaching_authority_unavailable") from exc
        if allowed is not True:
            if not required:
                return False
            raise cases.CaseConflict("teaching_action_denied")
        if (
            not isinstance(deadline, datetime)
            or timezone.is_naive(deadline)
            or not timezone.now() < deadline <= timezone.now() + timedelta(hours=1)
        ):
            raise cases.CaseConflict("teaching_finite_grant_required")
        self.deadlines.append(deadline)
        return True

    def permit(
        self, provider, actor, case, action, kind, identifier="", digest="", *, required=True
    ):
        values = dict(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            kind=kind,
            resource_id=str(identifier),
            resource_sha256=digest,
        )
        if not self._call(values, required=required):
            return False
        if values not in self.permissions:
            self.permissions.append(values)
        return True

    def source_permission(self, provider, subject, pin, kind):
        actor, case = self.actor(provider, subject, pin["case_id"])
        self.permit(provider, actor, case, "READ_SOURCE", kind, pin["id"], pin["sha256"])
        return actor, case

    def callbacks(self):
        for values in self.permissions:
            self._call(values)
        for provider, actor, case in tuple(self.identities.values()):
            fresh = cases._identity(provider, actor.subject_id, case)
            if library._actor(fresh) != library._actor(actor):
                raise cases.CaseConflict("teaching_identity_changed")
            self.deadlines.append(fresh.valid_until)

    def pure(self):
        enabled(public=self.public)
        authority, epoch = policy()
        current_history = history()
        if (
            authority is not self.authority
            or epoch != self.epoch
            or current_history != self.rows
            or any(current_history != pin for pin in self.read_pins)
        ):
            raise cases.CaseConflict("teaching_projection_changed")
        if (
            getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or library.identity_snapshot(self.directory) != self.directory_pin
        ):
            raise cases.CaseConflict("teaching_directory_changed")
        for provider, expected in self.provider_pins.values():
            if library.identity_snapshot(provider) != expected:
                raise cases.CaseConflict("teaching_identity_changed")
        if any(deadline <= timezone.now() for deadline in self.deadlines):
            raise cases.CaseConflict("teaching_grant_expired")
        self.source.pure()

    def before_write(self):
        self.callbacks()
        self.pure()

    def written(self):
        # Called immediately after the intended local SQL append, without an
        # intervening policy, identity, storage or render callback.
        self.rows = history()


@mutation_context
@contextmanager
def scope(*, extra_case_ids=()):
    existing = _CURRENT.get()
    if existing is not None:
        if not {cases._uuid(value) for value in extra_case_ids} <= set(existing.source.locked):
            raise cases.CaseConflict("teaching_nested_scope_expansion")
        yield existing
        return
    with synthetic_queue_atomic():
        policy_pin = policy()
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        directory_pin = library.identity_snapshot(directory)
        rows = history()
        with sources.boundary(extra_case_ids=extra_case_ids) as snapshot:
            guard = Guard(snapshot, policy_pin, directory, directory_pin, rows)
            guard.pure()
            token = _CURRENT.set(guard)
            try:
                yield guard
                guard.callbacks()
            finally:
                _CURRENT.reset(token)
        # All source byte/permission callbacks have finished. This check is pure.
        guard.pure()


@contextmanager
def staff_scope(*, case_id, subject_id, provider, synthetic_fixtures_only=False, **unused):
    enabled()
    if synthetic_fixtures_only is not True:
        raise cases.CaseConflict("synthetic_ack_required")
    before = library.identity_snapshot(provider)
    initial = resolve_identity(provider, subject_id)
    identifiers = set(
        Case.objects.filter(public_ref__in=initial.case_keys).values_list("pk", flat=True)
    ) | {cases._uuid(case_id)}
    with scope(extra_case_ids=identifiers) as guard:
        if library.identity_snapshot(provider) != before:
            raise cases.CaseConflict("teaching_identity_changed")
        actor, case = guard.actor(provider, subject_id, case_id)
        guard.permit(provider, actor, case, "READ", "WORKSPACE")
        yield guard, actor, case


def _verify(row):
    library._verify(row)
    actions, previous = list(row.actions.order_by("sequence")), row.digest
    for number, event in enumerate(actions, 1):
        library._verify(event)
        if event.sequence != number or event.previous_digest != previous:
            raise cases.CaseConflict("teaching_history_changed")
        previous = event.digest
    return actions


def _read_sources(guard, row, provider, subject, *, public=False, visiting=()):
    kind, source = row.item.kind, guard.source
    actor, owner = guard.actor(provider, subject, row.item.case_id)
    if kind == "SCHOLAR_MATERIAL":
        profile = source.record(row.profile_id, "SCHOLAR")
        checked = {
            "profile": source.record_pin(row.profile_id, "SCHOLAR"),
            "library": source.library_pin(row.library_version_id),
        }
        for name, pin in checked.items():
            guard.source_permission(
                provider, subject, pin, "SCHOLAR" if name == "profile" else "LIBRARY"
            )
        result = {
            "profile": source.pk.scholars[str(profile.pk)],
            "material": source.lib.read(row.library_version_id),
        }
    elif kind == "LESSON":
        metadata = source.record_pin(row.lesson_metadata_id, "LESSON")
        guard.source_permission(provider, subject, metadata, "LESSON_METADATA")
        checked, record, lesson = source.lesson_pins(
            row.lesson_metadata_id, provider=provider, actor=actor, content=True
        )
        for name in ("lesson", "series"):
            guard.source_permission(provider, subject, checked[name], name.upper())
        source_actor, source_case = guard.actor(provider, subject, checked["lesson"]["case_id"])
        if public:
            guard.permit(
                provider,
                source_actor,
                source_case,
                "PUBLIC_LESSON_CONTENT",
                "ANSWER_MEDIA",
                lesson.source_part_id,
                lesson.source_part.sha256,
            )
        if str(lesson.pk) != str(row.lesson_version_id) or str(lesson.series_version_id) != str(
            row.series_version_id
        ):
            raise cases.CaseConflict("teaching_lesson_version_changed")
        result = {"lesson": source.pk.lessons[str(record.pk)], "part": lesson.source_part}
    elif kind == "SERIES":
        series = source.series(row.series_version_id, provider=provider, actor=actor)
        checked = {"series": sources.pin(series, case_id=series.series.case_id)}
        guard.source_permission(provider, subject, checked["series"], "SERIES")
        if any(
            label not in [teacher["name"] for teacher in series.teachers]
            for label in row.teacher_labels
        ):
            raise cases.CaseConflict("teaching_teacher_attribution_changed")
        members, last = [], -1
        if not row.members or len(row.members) > 16:
            raise cases.CaseConflict("teaching_series_members_required")
        for pin in row.members:
            member = (
                TeachingVersion.objects.select_related("item", "lesson_version__lesson")
                .filter(pk=cases._uuid(pin["id"]))
                .first()
            )
            if (
                member is None
                or member.item.kind != "LESSON"
                or pin != sources.pin(member, case_id=member.item.case_id, digest=member.digest)
            ):
                raise cases.CaseConflict("teaching_series_member_changed")
            guard.source_permission(provider, subject, pin, "TEACHING_LESSON")
            if str(member.lesson_version.lesson_id) not in series.lesson_order:
                raise cases.CaseConflict("teaching_series_member_outside_source")
            position = series.lesson_order.index(str(member.lesson_version.lesson_id))
            if position <= last:
                raise cases.CaseConflict("teaching_documented_order_changed")
            last = position
            child = _released(guard, member, visiting=(*visiting, str(row.pk)))
            members.append(child)
        result = {"series": series, "members": members}
    else:
        raise cases.CaseConflict("teaching_kind_invalid")
    if checked != row.source_pins:
        raise cases.CaseConflict("teaching_exact_source_changed")
    return result


def _latest_released(item):
    return (
        TeachingVersion.objects.filter(item=item, actions__action="RELEASE")
        .order_by("-number")
        .first()
    )


def _privacy_sources(guard, row, release):
    """Current release identity admits exact sources without exposing originals."""
    actor, _ = guard.actor(
        guard.directory,
        release.subject_id,
        row.item.case_id,
        expected_epoch=release.auth_epoch,
        expected_provider=release.provider_id,
    )
    targets = []
    if row.item.kind == "SCHOLAR_MATERIAL":
        targets = [
            ("PUBLIC_KNOWLEDGE", row.profile_id),
            ("LIBRARY_VERSION", row.library_version_id),
        ]
    elif row.item.kind == "LESSON":
        targets = [
            ("PUBLIC_KNOWLEDGE", row.lesson_metadata_id),
            ("LESSON_VERSION", row.lesson_version_id),
            ("SERIES_VERSION", row.series_version_id),
            ("ANSWER_PART", row.lesson_version.source_part_id),
        ]
    elif row.item.kind == "SERIES":
        targets = [
            ("SERIES_VERSION", row.series_version_id),
            *(("PUBLIC_TEACHING", member["id"]) for member in row.members),
        ]
    for kind, identifier in targets:
        privacy.staff(kind, identifier, provider=guard.directory, actor=actor, action="PUBLISH")


def _released(guard, row, *, visiting=()):
    if str(row.pk) in visiting or len(visiting) > 2:
        raise cases.CaseConflict("teaching_member_cycle")
    actions = _verify(row)
    events = {event.action: event for event in actions}
    latest = _latest_released(row.item)
    if (
        latest is None
        or latest.pk != row.pk
        or "WITHDRAW" in events
        or not {"REVIEW", "APPROVE", "RELEASE"} <= set(events)
    ):
        raise cases.CaseConflict("teaching_current_release_required")
    if events["RELEASE"].valid_until <= timezone.now():
        raise cases.CaseConflict("teaching_release_expired")
    if guard.public:
        privacy.public("PUBLIC_TEACHING", row.pk)
        _privacy_sources(guard, row, events["RELEASE"])
    guard.deadlines.append(events["RELEASE"].valid_until)
    source = None
    for command in ("REVIEW", "APPROVE", "RELEASE"):
        event = events[command]
        actor, case = guard.actor(
            guard.directory,
            event.subject_id,
            row.item.case_id,
            expected_epoch=event.auth_epoch,
            expected_provider=event.provider_id,
        )
        guard.permit(guard.directory, actor, case, command, row.item.kind, row.pk, row.digest)
        source = _read_sources(
            guard,
            row,
            guard.directory,
            actor.subject_id,
            public=command == "RELEASE",
            visiting=visiting,
        )
    return _public_dto(row, source)


def _public_dto(row, source):
    dto = {
        "id": str(row.item.public_id),
        "number": row.number,
        "kind": row.item.kind,
        "title": row.title,
        "summary": row.summary,
        "topic": row.topic,
        "teacher_labels": list(row.teacher_labels),
    }
    if row.item.kind == "SCHOLAR_MATERIAL":
        dto.update(
            profile=source["profile"],
            material=source["material"],
            attribution=row.attribution,
            url=f"/library-preview/teaching/scholars/{source['profile']['id']}/",
        )
    elif row.item.kind == "LESSON":
        dto.update(
            lesson=source["lesson"],
            url=f"/library-preview/teaching/lessons/{row.item.public_id}/",
            audio_url=f"/library-preview/teaching/lessons/{row.item.public_id}/{row.number}/media/",
        )
    else:
        dto.update(
            members=source["members"], url=f"/library-preview/teaching/series/{row.item.public_id}/"
        )
    return dto


def _build(
    guard,
    *,
    kind,
    provider,
    actor,
    profile,
    material,
    lesson,
    series,
    members,
    teacher_labels,
    attribution,
    topic,
):
    values = dict(
        profile=None,
        library_version=None,
        lesson_metadata=None,
        lesson_version=None,
        series_version=None,
        members=[],
    )
    if kind == "SCHOLAR_MATERIAL":
        if lesson or series or members or teacher_labels or topic:
            raise cases.CaseConflict("teaching_attribution_fields_invalid")
        _text(attribution, 1000)
        profile_id, profile_sha = _selection(profile)
        material_id, material_sha = _selection(material)
        record = guard.source.record(profile_id, "SCHOLAR")
        material_pin = guard.source.library_pin(material_id)
        if record.sha256 != profile_sha or material_pin["sha256"] != material_sha:
            raise cases.CaseConflict("teaching_selection_changed")
        library_row = LibraryVersion.objects.select_related("item").get(pk=material_id)
        source_pins = {
            "profile": guard.source.record_pin(profile_id, "SCHOLAR"),
            "library": material_pin,
        }
        for name, pin in source_pins.items():
            guard.source_permission(
                provider, actor.subject_id, pin, "SCHOLAR" if name == "profile" else "LIBRARY"
            )
        values.update(profile=record, library_version=library_row)
        external_id, secondary_id = record.series_id, library_row.item_id
    elif kind == "LESSON":
        if profile or material or series or members or teacher_labels or topic or attribution:
            raise cases.CaseConflict("teaching_lesson_fields_invalid")
        identifier, digest = _selection(lesson)
        metadata_pin = guard.source.record_pin(identifier, "LESSON")
        if metadata_pin["sha256"] != digest:
            raise cases.CaseConflict("teaching_selection_changed")
        guard.source_permission(provider, actor.subject_id, metadata_pin, "LESSON_METADATA")
        source_pins, record, version = guard.source.lesson_pins(
            identifier, provider=provider, actor=actor, content=True
        )
        for name in ("lesson", "series"):
            guard.source_permission(provider, actor.subject_id, source_pins[name], name.upper())
        values.update(
            lesson_metadata=record, lesson_version=version, series_version=version.series_version
        )
        external_id, secondary_id = record.series_id, None
    elif kind == "SERIES":
        if profile or material or lesson or attribution or not members or len(members) > 16:
            raise cases.CaseConflict("teaching_series_fields_invalid")
        identifier, digest = _selection(series)
        version = guard.source.series(identifier, provider=provider, actor=actor)
        if version.sha256 != digest:
            raise cases.CaseConflict("teaching_selection_changed")
        source_pins = {"series": sources.pin(version, case_id=version.series.case_id)}
        guard.source_permission(provider, actor.subject_id, source_pins["series"], "SERIES")
        if any(
            label not in [teacher["name"] for teacher in version.teachers]
            for label in teacher_labels
        ):
            raise cases.CaseConflict("teaching_teacher_attribution_changed")
        selected, last = [], -1
        for token in members:
            member_id, member_sha = _selection(token)
            member = (
                TeachingVersion.objects.select_related("item", "lesson_version__lesson")
                .filter(pk=member_id, item__kind="LESSON")
                .first()
            )
            if member is None or member.digest != member_sha:
                raise cases.CaseConflict("teaching_member_selection_changed")
            member_pin = sources.pin(member, case_id=member.item.case_id, digest=member.digest)
            guard.source_permission(provider, actor.subject_id, member_pin, "TEACHING_LESSON")
            _released(guard, member)
            lesson_id = str(member.lesson_version.lesson_id)
            if lesson_id not in version.lesson_order:
                raise cases.CaseConflict("teaching_series_member_outside_source")
            position = version.lesson_order.index(lesson_id)
            if position <= last:
                raise cases.CaseConflict("teaching_documented_order_changed")
            last = position
            selected.append(member_pin)
        values.update(series_version=version, members=selected)
        external_id, secondary_id = version.series.public_id, None
    else:
        raise cases.CaseConflict("teaching_kind_invalid")
    return values, source_pins, external_id, secondary_id


def _audit(base, actor, case, key, request_sha, note):
    return dict(
        provider_id=base["provider"].provider_id,
        subject_id=actor.subject_id,
        auth_epoch=actor.auth_epoch,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        request_key=key,
        request_sha256=request_sha,
        note=note,
    )


def _replay(old, expected, actor, base):
    if old is not None and (
        old.request_sha256 != expected
        or old.provider_id != base["provider"].provider_id
        or old.subject_id != actor.subject_id
    ):
        raise cases.CaseConflict("teaching_request_conflict")
    return old


@mutation_service
def save(
    *,
    kind,
    title,
    summary="",
    topic="",
    teacher_labels=None,
    attribution="",
    profile="",
    material="",
    lesson="",
    series="",
    members=None,
    item_id=None,
    expected_version=0,
    expected_revision,
    expected_evidence_version,
    request_key,
    note,
    confirmed=False,
    **base,
):
    if confirmed is not True or kind not in KINDS:
        raise cases.CaseConflict("teaching_human_confirmation_required")
    _text(title, 160), _text(summary, 2000, optional=True), _text(topic, 160, optional=True)
    _text(attribution, 1000, optional=True), _text(note, 1000)
    teacher_labels = [] if teacher_labels is None else teacher_labels
    members = [] if members is None else members
    if (
        type(teacher_labels) is not list
        or len(teacher_labels) > 8
        or any(type(value) is not str for value in teacher_labels)
        or len(set(teacher_labels)) != len(teacher_labels)
        or type(members) is not list
    ):
        raise cases.CaseConflict("teaching_collection_fields_invalid")
    for label in teacher_labels:
        _text(label, 120)
    _zero(expected_version)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    key = cases._uuid(request_key)
    requested = library._digest(
        dict(
            kind=kind,
            title=title,
            summary=summary,
            topic=topic,
            teacher_labels=teacher_labels,
            attribution=attribution,
            profile=profile,
            material=material,
            lesson=lesson,
            series=series,
            members=members,
            item_id=str(item_id or ""),
            expected_version=expected_version,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
            note=note,
            case_id=str(base["case_id"]),
        )
    )
    with staff_scope(**base) as (guard, actor, case):
        guard.permit(base["provider"], actor, case, "WRITE", kind, item_id or "")
        cases._versions(case, expected_revision, expected_evidence_version)
        old = _replay(
            TeachingVersion.objects.filter(request_key=key).first(), requested, actor, base
        )
        if old:
            if old.item.case_id != case.pk:
                raise cases.CaseConflict("teaching_request_conflict")
            return _staff_row(guard, old, base["provider"], actor)
        fields, source_pins, external_id, secondary_id = _build(
            guard,
            kind=kind,
            provider=base["provider"],
            actor=actor,
            profile=profile,
            material=material,
            lesson=lesson,
            series=series,
            members=members,
            teacher_labels=teacher_labels,
            attribution=attribution,
            topic=topic,
        )
        if item_id:
            item = TeachingItem.objects.filter(pk=cases._uuid(item_id), case=case).first()
            if item is None or (item.kind, item.external_id, item.secondary_id) != (
                kind,
                external_id,
                secondary_id,
            ):
                raise cases.CaseConflict("teaching_stable_identity_changed")
            previous = item.versions.order_by("-number").first()
            if previous is None or previous.number != expected_version or previous.number >= 64:
                raise cases.CaseConflict("teaching_version_changed")
        else:
            if (
                expected_version != 0
                or TeachingItem.objects.filter(
                    kind=kind, external_id=external_id, secondary_id=secondary_id
                ).exists()
            ):
                raise cases.CaseConflict("teaching_existing_identity_required")
            item, previous = (
                TeachingItem(
                    case=case, kind=kind, external_id=external_id, secondary_id=secondary_id
                ),
                None,
            )
        guard.before_write()
        case.refresh_from_db()
        cases._versions(case, expected_revision, expected_evidence_version)
        if item._state.adding:
            item.save(force_insert=True)
        row = library._seal(
            TeachingVersion(
                item=item,
                number=1 if previous is None else previous.number + 1,
                previous_digest="0" * 64 if previous is None else previous.digest,
                title=title,
                summary=summary,
                topic=topic,
                teacher_labels=teacher_labels,
                attribution=attribution,
                source_pins=source_pins,
                **fields,
                **_audit(base, actor, case, key, requested, note),
            )
        )
        guard.written()
        return _staff_row(guard, row, base["provider"], actor)


@mutation_service
def decide(
    *,
    version_id,
    command,
    expected_actions,
    expected_revision,
    expected_evidence_version,
    request_key,
    note,
    confirmed=False,
    minutes=0,
    **base,
):
    if confirmed is not True or command not in COMMANDS:
        raise cases.CaseConflict("teaching_human_confirmation_required")
    _text(note, 1000)
    if type(expected_actions) is not int or not 0 <= expected_actions <= 4:
        raise cases.CaseConflict("teaching_action_count_invalid")
    if (
        type(minutes) is not int
        or (command == "RELEASE" and minutes not in (5, 15, 30, 60))
        or (command != "RELEASE" and minutes != 0)
    ):
        raise cases.CaseConflict("teaching_release_duration_invalid")
    cases._mutation_versions(expected_revision, expected_evidence_version)
    key = cases._uuid(request_key)
    requested = library._digest(
        dict(
            version_id=str(version_id),
            command=command,
            expected_actions=expected_actions,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
            minutes=minutes,
            note=note,
            case_id=str(base["case_id"]),
        )
    )
    with staff_scope(**base) as (guard, actor, case):
        cases._versions(case, expected_revision, expected_evidence_version)
        row = (
            TeachingVersion.objects.select_related("item")
            .filter(pk=cases._uuid(version_id), item__case=case)
            .first()
        )
        if row is None:
            raise cases.CaseConflict("teaching_version_unavailable")
        guard.permit(base["provider"], actor, case, command, row.item.kind, row.pk, row.digest)
        old = _replay(
            TeachingAction.objects.filter(request_key=key).first(), requested, actor, base
        )
        if old:
            if old.version_id != row.pk:
                raise cases.CaseConflict("teaching_request_conflict")
            return _staff_row(guard, row, base["provider"], actor)
        actions = _verify(row)
        names = {event.action for event in actions}
        if len(actions) != expected_actions or "WITHDRAW" in names:
            raise cases.CaseConflict("teaching_action_changed")
        if command != "WITHDRAW":
            if row.item.versions.order_by("-number").first().pk != row.pk:
                raise cases.CaseConflict("teaching_latest_draft_required")
            expected = {"REVIEW": [], "APPROVE": ["REVIEW"], "RELEASE": ["REVIEW", "APPROVE"]}[
                command
            ]
            if [event.action for event in actions] != expected:
                raise cases.CaseConflict("teaching_action_order_invalid")
            identity = base["provider"].provider_id, actor.subject_id
            if identity == (row.provider_id, row.subject_id) or (
                command in {"APPROVE", "RELEASE"}
                and identity == (actions[0].provider_id, actions[0].subject_id)
            ):
                raise cases.CaseConflict("teaching_independent_actor_required")
            _read_sources(
                guard, row, base["provider"], actor.subject_id, public=command == "RELEASE"
            )
        guard.before_write()
        case.refresh_from_db()
        cases._versions(case, expected_revision, expected_evidence_version)
        deadline = (
            min(
                timezone.now() + timedelta(minutes=minutes),
                *guard.deadlines,
                *guard.source.deadlines,
            )
            if command == "RELEASE"
            else None
        )
        library._seal(
            TeachingAction(
                version=row,
                sequence=len(actions) + 1,
                previous_digest=actions[-1].digest if actions else row.digest,
                action=command,
                valid_until=deadline,
                **_audit(base, actor, case, key, requested, note),
            )
        )
        guard.written()
        return _staff_row(guard, row, base["provider"], actor)


def _staff_row(guard, row, provider, actor):
    owner_actor, case = guard.actor(provider, actor.subject_id, row.item.case_id)
    guard.permit(provider, owner_actor, case, "READ", row.item.kind, row.pk, row.digest)
    actions = _verify(row)
    state = actions[-1].action if actions else "DRAFT"
    latest = row.item.versions.order_by("-number").first().pk == row.pk
    options = []
    if state != "WITHDRAW":
        next_action = {"DRAFT": "REVIEW", "REVIEW": "APPROVE", "APPROVE": "RELEASE"}.get(state)
        for command in [*([next_action] if next_action and latest else []), "WITHDRAW"]:
            if command != "WITHDRAW" and (
                (provider.provider_id, actor.subject_id) == (row.provider_id, row.subject_id)
                or (
                    command in {"APPROVE", "RELEASE"}
                    and actions
                    and (provider.provider_id, actor.subject_id)
                    == (actions[0].provider_id, actions[0].subject_id)
                )
            ):
                continue
            if guard.permit(
                provider, actor, case, command, row.item.kind, row.pk, row.digest, required=False
            ):
                options.append({"command": command, "label": LABELS[command]})
    review_control = None
    if row.item.kind == "LESSON" and str(row.lesson_metadata_id) in guard.source.pk.records:
        try:
            original = _read_sources(guard, row, provider, actor.subject_id)
            owner = original["part"].manifest.answer.case
            review_control = {
                "case_ref": owner.public_ref,
                "lesson_version_id": str(row.lesson_version_id),
            }
        except cases.CaseConflict:
            # Only own currently granted curation history is shown below. No
            # previous source metadata or bytes is replayed as an available file.
            pass
    return {
        "id": str(row.pk),
        "item_id": str(row.item_id),
        "public_id": str(row.item.public_id),
        "kind": row.item.kind,
        "kind_label": KINDS[row.item.kind],
        "number": row.number,
        "digest": row.digest,
        "selection": selection(row),
        "title": row.title,
        "summary": row.summary,
        "topic": row.topic,
        "teacher_labels": row.teacher_labels,
        "attribution": row.attribution,
        "note": row.note,
        "state": state,
        "state_label": LABELS[state],
        "action_count": len(actions),
        "options": options,
        "actor": row.subject_id,
        "created_at": row.created_at,
        "latest": latest,
        "review_control": review_control,
        "history": [
            {
                "command": event.action,
                "label": LABELS[event.action],
                "note": event.note,
                "actor": event.subject_id,
                "created_at": event.created_at,
                "valid_until": event.valid_until,
            }
            for event in actions
        ],
    }


def _can_source(guard, provider, actor, pin, kind):
    try:
        current, owner = guard.actor(provider, actor.subject_id, pin["case_id"])
        return guard.permit(
            provider, current, owner, "READ_SOURCE", kind, pin["id"], pin["sha256"], required=False
        )
    except cases.CaseConflict:
        return False


def _choices(guard, provider, actor):
    result = {"profiles": [], "materials": [], "lessons": [], "series": [], "members": []}
    for identifier, record in guard.source.pk.records.items():
        if record.series.kind not in {"SCHOLAR", "LESSON"}:
            continue
        pin = guard.source.record_pin(identifier, record.series.kind)
        if not _can_source(
            guard,
            provider,
            actor,
            pin,
            "LESSON_METADATA" if record.series.kind == "LESSON" else "SCHOLAR",
        ):
            continue
        if record.series.kind == "SCHOLAR":
            result["profiles"].append(
                {"selection": selection(record), "label": record.payload["name"]}
            )
        else:
            try:
                _, version = guard.source.lesson(identifier, provider=provider, actor=actor)
                if not _can_source(
                    guard,
                    provider,
                    actor,
                    sources.pin(version, case_id=version.lesson.series.case_id),
                    "LESSON",
                ):
                    continue
            except cases.CaseConflict:
                continue
            result["lessons"].append(
                {"selection": selection(record), "label": record.payload["title"]}
            )
    for identifier, row in guard.source.lib.records.items():
        pin = guard.source.library_pin(identifier)
        if _can_source(guard, provider, actor, pin, "LIBRARY"):
            result["materials"].append(
                {
                    "selection": f"{identifier}|{row['digest']}",
                    "label": f"{row['title']} · النسخة {row['number']}",
                }
            )
    latest_series, seen = {}, set()
    for row in (
        SeriesVersion.objects.select_related("series")
        .filter(series__case_id__in=guard.source.locked)
        .order_by("series_id", "-number")
    ):
        if row.series_id in seen:
            continue
        seen.add(row.series_id)
        if not _can_source(
            guard, provider, actor, sources.pin(row, case_id=row.series.case_id), "SERIES"
        ):
            continue
        try:
            guard.source.series(row.pk, provider=provider, actor=actor)
        except cases.CaseConflict:
            continue
        latest_series[row.series_id] = row
        result["series"].append(
            {
                "selection": selection(row),
                "label": f"{row.title} · النسخة {row.number}",
                "teachers": "\n".join(teacher["name"] for teacher in row.teachers),
            }
        )
    ordered = []
    for row in TeachingVersion.objects.select_related("item", "lesson_version__lesson").filter(
        item__kind="LESSON", actions__action="RELEASE"
    ):
        series = latest_series.get(row.lesson_version.lesson.series_id)
        if series is None or str(row.lesson_version.lesson_id) not in series.lesson_order:
            continue
        pin = sources.pin(row, case_id=row.item.case_id, digest=row.digest)
        if not _can_source(guard, provider, actor, pin, "TEACHING_LESSON"):
            continue
        try:
            dto = _released(guard, row)
        except cases.CaseConflict:
            continue
        position = series.lesson_order.index(str(row.lesson_version.lesson_id))
        ordered.append(
            (
                str(series.series_id),
                position,
                {
                    "selection": selection(row),
                    "label": f"{series.title} · الموضع {position + 1}: {dto['title']}",
                },
            )
        )
    result["members"] = [row for _, _, row in sorted(ordered, key=lambda value: value[:2])]
    return result


def desk_locked(guard, actor, case, provider):
    rows = []
    for row in (
        TeachingVersion.objects.select_related("item")
        .filter(item__case=case)
        .order_by("item_id", "-number")
    ):
        if not guard.permit(
            provider, actor, case, "READ", row.item.kind, row.pk, row.digest, required=False
        ):
            continue
        rows.append(_staff_row(guard, row, provider, actor))
    case.refresh_from_db()
    return {
        "case_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "versions": rows,
        "choices": _choices(guard, provider, actor),
        "kinds": [{"value": key, "label": label} for key, label in KINDS.items()],
    }


@mutation_context
@contextmanager
def desk_projection(**base):
    with staff_scope(**base) as (guard, actor, case):
        before = history()
        guard.read_pins.append(before)
        result = desk_locked(guard, actor, case, base["provider"])
        guard.pure()
        yield result
        if history() != before:
            raise cases.CaseConflict("teaching_read_history_changed")


class PublicSnapshot:
    def __init__(self, guard):
        self.guard = guard
        self.rows = {}
        candidates = (
            TeachingVersion.objects.select_related("item")
            .filter(actions__action="RELEASE")
            .order_by("item_id", "-number")
        )
        seen = set()
        for row in candidates:
            if row.item_id in seen:
                continue
            seen.add(row.item_id)
            try:
                dto = _released(guard, row)
            except cases.CaseConflict:
                continue
            self.rows[str(row.item.public_id)] = (row, dto)

    def read(self, identifier, kind):
        entry = self.rows.get(str(identifier))
        if entry is None or entry[0].item.kind != kind:
            raise preview.PreviewUnavailable()
        return entry

    def catalog(self):
        return {
            "lessons": [dto for row, dto in self.rows.values() if row.item.kind == "LESSON"],
            "series": [dto for row, dto in self.rows.values() if row.item.kind == "SERIES"],
            "scholars": {
                dto["profile"]["id"]: dto["profile"]
                for row, dto in self.rows.values()
                if row.item.kind == "SCHOLAR_MATERIAL"
            }.values(),
        }

    def scholar(self, identifier):
        current = self.guard.source.pk.scholar(identifier)
        materials = [
            dto
            for row, dto in self.rows.values()
            if row.item.kind == "SCHOLAR_MATERIAL" and dto["profile"]["id"] == str(identifier)
        ]
        return {**current, "materials": materials}

    def lesson(self, identifier, *, series_id=None):
        _, result = self.read(identifier, "LESSON")
        result = {**result, "series": None, "previous": None, "next": None}
        if series_id is not None:
            _, series = self.read(series_id, "SERIES")
            ids = [member["id"] for member in series["members"]]
            if str(identifier) not in ids:
                raise preview.PreviewUnavailable()
            position = ids.index(str(identifier))
            if series["members"][position]["number"] != result["number"]:
                raise preview.PreviewUnavailable()
            result["series"] = series
            for key, offset in (("previous", -1), ("next", 1)):
                if 0 <= position + offset < len(ids):
                    other = series["members"][position + offset]
                    result[key] = {
                        "title": other["title"],
                        "url": f"/library-preview/teaching/series/{series_id}/lessons/{other['id']}/",
                    }
        return result

    def audio(self, identifier, number):
        row, _ = self.read(identifier, "LESSON")
        if row.number != number:
            raise preview.PreviewUnavailable()
        part = row.lesson_version.source_part
        from apps.answer_media import services as media

        raw = media.raw_for_part(part)
        self.guard.source.parts[str(part.pk)] = (part, row.lesson_version.source_snapshot)
        return {
            "raw": raw,
            "media_type": part.media_type,
            "filename": f"lesson-{row.item.public_id}-v{row.number}."
            + (
                "wav"
                if part.media_type == "audio/wav"
                else "mp3"
                if part.media_type == "audio/mpeg"
                else "audio"
            ),
        }


@mutation_context
@privacy.public_contextual
@contextmanager
def public_projection():
    try:
        enabled(public=True)
        with scope() as guard:
            guard.public = True
            before = history()
            guard.read_pins.append(before)
            result = PublicSnapshot(guard)
            guard.pure()
            yield result
            if history() != before:
                raise cases.CaseConflict("teaching_read_history_changed")
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
