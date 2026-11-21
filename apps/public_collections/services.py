"""Human curation with exact cross-case pins, append-only audit and current grants."""

import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.library_preview import services as preview
from apps.platform_recovery.integration import mutation_context, mutation_service
from apps.public_knowledge.services import _digest, _identity_tuple, _text

from . import sources
from .authority import CollectionAuthority
from .models import CollectionAction, CollectionRevision, CollectionSeries

KINDS = {"TOPIC": "موضوع", "COLLECTION": "مجموعة منتقاة", "HOME": "اختيارات الصفحة الرئيسية"}
STAGES = {"DRAFT": "مسودة", "REVIEWED": "مراجعة", "APPROVED": "معتمدة", "WITHDRAWN": "مسحوبة"}
MAX_MEMBERS = 16


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLIC_COLLECTIONS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("public_collections_disabled")


def epoch():
    policy = getattr(settings, "FATWA_PUBLIC_COLLECTIONS_AUTHORITY", None)
    if not isinstance(policy, CollectionAuthority):
        raise cases.CaseConflict("collection_authority_required")
    try:
        value = policy.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("collection_authority_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 2000:
        raise cases.CaseConflict("collection_authority_snapshot_required")
    return policy, value


def history():
    return (
        list(CollectionSeries.objects.order_by("pk").values()),
        list(CollectionRevision.objects.order_by("pk").values()),
        list(CollectionAction.objects.order_by("pk").values()),
    )


def identity_epoch(directory):
    """Required only by this composed feature, never an identity or access grant.

    An atomic, side-effect-free directory generation covers every subject's
    active state, role, case scope, authorization epoch and expiry. A final
    callback in a different public reader can otherwise revoke an actor whose
    identity was checked earlier in the assembled response.
    """
    try:
        value = directory.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("collection_identity_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 2000:
        raise cases.CaseConflict("collection_identity_snapshot_required")
    return value


class Guard:
    def __init__(self, source_snapshot, directory, directory_epoch):
        self.source = source_snapshot
        self.policy, self.epoch = epoch()
        self.directory, self.directory_epoch = directory, directory_epoch
        self.checks, self.identities, self.deadlines = [], [], []

    def actor(self, provider, subject, case_id):
        case = self.source.locked.get(cases._uuid(case_id))
        if case is None:
            raise cases.CaseConflict("collection_case_unavailable")
        actor = cases._identity(provider, subject, case)
        self.identities.append((provider, provider.provider_id, actor, case))
        self.deadlines.append(actor.valid_until)
        return actor, case

    def permit(self, provider, actor, case, action, kind, identifier="", digest=""):
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
        self._call(values)
        if values not in self.checks:
            self.checks.append(values)

    def _call(self, values):
        try:
            allowed = self.policy.permits(**values)
        except Exception as exc:
            raise cases.CaseConflict("collection_authority_unavailable") from exc
        if allowed is not True:
            raise cases.CaseConflict("collection_action_denied")

    def member(self, pin, provider, actor):
        current, case = self.actor(provider, actor.subject_id, pin["case_id"])
        if _identity_tuple(current) != _identity_tuple(actor):
            raise cases.CaseConflict("collection_identity_changed")
        self.permit(provider, current, case, "READ_MEMBER", pin["kind"], pin["id"], pin["sha256"])
        return self.source.read(pin)

    def callbacks(self):
        for values in self.checks:
            self._call(values)
        for provider, namespace, actor, case in self.identities:
            fresh = cases._identity(provider, actor.subject_id, case)
            if provider.provider_id != namespace or _identity_tuple(fresh) != _identity_tuple(
                actor
            ):
                raise cases.CaseConflict("collection_identity_changed")
            self.deadlines.append(fresh.valid_until)

    def final_pins(self):
        policy, value = epoch()
        if (
            policy is not self.policy
            or value != self.epoch
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or identity_epoch(self.directory) != self.directory_epoch
        ):
            raise cases.CaseConflict("collection_policy_changed")
        if any(deadline <= timezone.now() for deadline in self.deadlines):
            raise cases.CaseConflict("collection_identity_or_release_expired")
        enabled()


@mutation_context
@contextmanager
def scope(*, extra_case_ids=(), freeze_history=False):
    enabled()
    with synthetic_queue_atomic():
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        directory_epoch = identity_epoch(directory)
        with sources.boundary(extra_case_ids=extra_case_ids) as source_snapshot:
            before = history() if freeze_history else None
            guard = Guard(source_snapshot, directory, directory_epoch)
            yield guard
            guard.callbacks()
            guard.final_pins()
        # Source readers run callbacks on exit. These final checks deliberately
        # follow all of them and remain inside the same outer transaction.
        guard.final_pins()
        if freeze_history and history() != before:
            raise cases.CaseConflict("collection_history_changed_during_read")


def fingerprint(record):
    return _digest(
        [
            str(record.series_id),
            record.number,
            record.case_revision,
            record.evidence_version,
            str(record.parent_id) if record.parent_id else "",
            record.payload,
            record.provider_id,
            record.subject_id,
            record.auth_epoch,
            str(record.request_key),
        ]
    )


def validate_payload(kind, payload):
    if (
        kind not in KINDS
        or type(payload) is not dict
        or set(payload) != {"title", "introduction", "members", "featured"}
    ):
        raise cases.CaseConflict("collection_payload_invalid")
    _text(payload["title"], 160)
    _text(payload["introduction"], 4000, optional=True)
    members = payload["members"]
    if (
        type(payload["featured"]) is not bool
        or type(members) is not list
        or not (0 if kind == "TOPIC" else 1) <= len(members) <= MAX_MEMBERS
    ):
        raise cases.CaseConflict("collection_members_bound")
    seen = set()
    for pin in members:
        if (
            type(pin) is not dict
            or set(pin) != {"kind", "id", "sha256", "number", "case_id"}
            or pin["kind"] not in sources.KINDS
        ):
            raise cases.CaseConflict("collection_member_pin_invalid")
        if (
            str(cases._uuid(pin["id"])) != pin["id"]
            or str(cases._uuid(pin["case_id"])) != pin["case_id"]
        ):
            raise cases.CaseConflict("collection_member_pin_invalid")
        if (
            type(pin["number"]) is not int
            or not 1 <= pin["number"] <= 1000000
            or type(pin["sha256"]) is not str
            or len(pin["sha256"]) != 64
            or set(pin["sha256"]) - set("0123456789abcdef")
        ):
            raise cases.CaseConflict("collection_member_pin_invalid")
        key = pin["kind"], pin["id"]
        if key in seen:
            raise cases.CaseConflict("collection_duplicate_member")
        seen.add(key)


def verify(record):
    validate_payload(record.series.kind, record.payload)
    if record.sha256 != fingerprint(record):
        raise cases.CaseConflict("collection_record_changed")
    events = list(record.actions.order_by("sequence"))
    stage, reviewer, approval, lease, revoked = "DRAFT", None, None, None, set()
    for expected, event in enumerate(events, 1):
        if event.sequence != expected or event.content_sha256 != record.sha256:
            raise cases.CaseConflict("collection_history_invalid")
        actor = event.provider_id, event.subject_id
        creator = record.provider_id, record.subject_id
        if event.action == "REVIEW" and stage == "DRAFT" and actor != creator:
            stage, reviewer = "REVIEWED", actor
        elif event.action == "APPROVE" and stage == "REVIEWED" and actor not in {creator, reviewer}:
            stage, approval = "APPROVED", event
        elif (
            event.action == "RELEASE"
            and stage == "APPROVED"
            and event.requested_minutes in {5, 15, 30, 60}
            and event.expires_at is not None
        ):
            lease = event
        elif event.action == "REVOKE" and stage == "APPROVED" and event.related_id is not None:
            if event.related_id in revoked or not any(
                old.pk == event.related_id
                and old.action == "RELEASE"
                and old.sequence < event.sequence
                for old in events
            ):
                raise cases.CaseConflict("collection_revocation_invalid")
            revoked.add(event.related_id)
        elif event.action == "WITHDRAW" and stage != "WITHDRAWN":
            stage = "WITHDRAWN"
        else:
            raise cases.CaseConflict("collection_action_invalid")
    if (
        stage != "APPROVED"
        or lease is not None
        and (lease.pk in revoked or lease.expires_at <= timezone.now())
    ):
        lease = None
    return events, stage, approval, lease


def current(identifier):
    row = (
        CollectionRevision.objects.select_related("series__case", "parent__series")
        .filter(pk=cases._uuid(identifier))
        .first()
    )
    if row is None or row.series.revisions.order_by("-number").first().pk != row.pk:
        raise cases.CaseConflict("collection_revision_unavailable")
    verify(row)
    return row


def _record_permission(guard, provider, actor, record, action):
    fresh, case = guard.actor(provider, actor.subject_id, record.series.case_id)
    if _identity_tuple(fresh) != _identity_tuple(actor):
        raise cases.CaseConflict("collection_identity_changed")
    guard.permit(provider, fresh, case, action, record.series.kind, record.pk, record.sha256)


def available(guard, *, public=False, search=False):
    """Only complete current collections. No omitted-member count or title leaks."""
    rows = list(
        CollectionRevision.objects.select_related("series__case", "parent__series").order_by(
            "series_id", "-number"
        )
    )
    if len(rows) > 4096:
        raise cases.CaseConflict("collection_history_bound")
    latest, result = {}, {}
    for row in rows:
        latest.setdefault(row.series_id, row)
    if len(latest) > 256:
        raise cases.CaseConflict("collection_public_bound")
    for row in latest.values():
        _, stage, approval, lease = verify(row)
        if stage != "APPROVED" or lease is None:
            continue
        try:
            if public:
                privacy.public("PUBLIC_COLLECTION", row.pk)
                if search:
                    privacy.public("PUBLIC_COLLECTION", row.pk, action="SEARCH")
                actor, _ = guard.actor(guard.directory, lease.subject_id, row.series.case_id)
                if (
                    guard.directory.provider_id != lease.provider_id
                    or actor.auth_epoch != lease.auth_epoch
                ):
                    raise cases.CaseConflict("collection_release_identity_changed")
                targets = [
                    (
                        "PUBLICATION"
                        if pin["kind"] == "PUBLICATION"
                        else "LIBRARY_VERSION"
                        if pin["kind"] == "LIBRARY"
                        else "PUBLIC_KNOWLEDGE",
                        pin["id"],
                    )
                    for pin in row.payload["members"]
                ]
                if row.parent_id:
                    targets.append(("PUBLIC_COLLECTION", row.parent_id))
                for kind, identifier in targets:
                    if search:
                        privacy.public(kind, identifier, action="SEARCH")
                    privacy.staff(
                        kind, identifier, provider=guard.directory, actor=actor, action="PUBLISH"
                    )
            cards = None
            for event in (approval, lease):
                directory = guard.directory
                if directory is None or directory.provider_id != event.provider_id:
                    raise cases.CaseConflict("collection_release_identity_unavailable")
                actor, case = guard.actor(directory, event.subject_id, row.series.case_id)
                if actor.auth_epoch != event.auth_epoch:
                    raise cases.CaseConflict("collection_release_identity_changed")
                guard.permit(
                    directory, actor, case, event.action, row.series.kind, row.pk, row.sha256
                )
                cards = [guard.member(pin, directory, actor) for pin in row.payload["members"]]
            guard.deadlines.append(lease.expires_at)
            result[str(row.pk)] = {"record": row, "cards": cards}
        except cases.CaseConflict:
            continue
    # Exact parent version is a dependency, never a floating topic name.
    for _ in range(6):
        missing = [
            key
            for key, value in result.items()
            if value["record"].parent_id and str(value["record"].parent_id) not in result
        ]
        if not missing:
            break
        for key in missing:
            del result[key]
    return result


def _parent(guard, provider, actor, *, parent_id, series_id, kind):
    if not parent_id:
        return None
    if kind != "TOPIC":
        raise cases.CaseConflict("only_topic_has_parent")
    published = available(guard)
    key = str(cases._uuid(parent_id))
    if key not in published:
        raise cases.CaseConflict("collection_parent_unavailable")
    parent = published[key]["record"]
    seen = {series_id} if series_id else set()
    cursor = parent
    while cursor is not None:
        if cursor.series.kind != "TOPIC" or cursor.series_id in seen or len(seen) >= 5:
            raise cases.CaseConflict("collection_parent_cycle_or_depth")
        seen.add(cursor.series_id)
        _record_permission(guard, provider, actor, cursor, "READ")
        cursor = None if cursor.parent_id is None else published[str(cursor.parent_id)]["record"]
    return parent


def _staff_row(record, guard, provider, actor):
    events, stage, _, lease = verify(record)
    _record_permission(guard, provider, actor, record, "READ")
    visible, members = True, []
    try:
        for pin in record.payload["members"]:
            card = guard.member(pin, provider, actor)
            members.append({**card, "selection": sources.selection(pin)})
        if record.parent_id:
            _parent(
                guard,
                provider,
                actor,
                parent_id=record.parent_id,
                series_id=record.series_id,
                kind=record.series.kind,
            )
    except cases.CaseConflict:
        visible, members = False, []
    return {
        "id": str(record.pk),
        "series_id": str(record.series_id),
        "public_id": str(record.series.public_id),
        "number": record.number,
        "kind": record.series.kind,
        "kind_label": KINDS[record.series.kind],
        "title": record.payload["title"] if visible else "محتوى غير متاح للصلاحيات الحالية",
        "introduction": record.payload["introduction"] if visible else "",
        "featured": record.payload["featured"],
        "members": members,
        "available": visible,
        "parent_id": str(record.parent_id) if visible and record.parent_id else "",
        "stage": stage,
        "stage_label": STAGES[stage],
        "action_count": len(events),
        "lease_id": str(lease.pk) if lease else "",
        "lease_until": lease.expires_at if lease else None,
        "history": [
            {
                "action": event.action,
                "actor": event.subject_id,
                "created_at": event.created_at,
                "note": event.note if visible else "",
            }
            for event in events
        ],
        "sha256": record.sha256,
    }


def desk_locked(guard, *, case_id, subject_id, provider, selected_id=None):
    actor, case = guard.actor(provider, subject_id, case_id)
    for kind in KINDS:
        guard.permit(provider, actor, case, "READ", kind)
    rows = []
    for series in CollectionSeries.objects.filter(case=case).order_by("created_at"):
        record = series.revisions.order_by("-number").first()
        if record is not None:
            value = _staff_row(record, guard, provider, actor)
            value["versions"] = [
                {"id": str(old.pk), "number": old.number}
                for old in series.revisions.order_by("-number")
            ]
            rows.append(value)
    selected = None
    if selected_id:
        record = (
            CollectionRevision.objects.select_related("series__case")
            .filter(pk=cases._uuid(selected_id), series__case=case)
            .first()
        )
        if record is None:
            raise cases.CaseConflict("collection_revision_unavailable")
        selected = _staff_row(record, guard, provider, actor)
    choices = []
    for member in guard.source.members.values():
        try:
            card = guard.member(member["pin"], provider, actor)
            choices.append({**card, "selection": sources.selection(member["pin"])})
        except cases.CaseConflict:
            continue
    parents = []
    for entry in available(guard).values():
        row = entry["record"]
        if row.series.kind != "TOPIC":
            continue
        try:
            _record_permission(guard, provider, actor, row, "READ")
            parents.append(
                {"id": str(row.pk), "title": row.payload["title"], "version": row.number}
            )
        except cases.CaseConflict:
            continue
    if len(choices) > 256:
        raise cases.CaseConflict("collection_choices_bound")
    return {
        "case_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "records": rows,
        "selected": selected,
        "choices": choices,
        "parents": parents,
        "kinds": KINDS.items(),
    }


@mutation_service
def save(
    *,
    case_id,
    subject_id,
    provider,
    kind,
    title,
    introduction,
    members,
    featured,
    expected_version,
    expected_revision,
    expected_evidence_version,
    request_key,
    series_id="",
    parent_id="",
    synthetic_fixtures_only=False,
):
    enabled()
    cases._guard(synthetic_fixtures_only)
    if (
        kind not in KINDS
        or type(expected_version) is not int
        or not 0 <= expected_version < 128
        or type(members) is not list
        or len(members) > MAX_MEMBERS
        or type(featured) is not bool
    ):
        raise cases.CaseConflict("collection_command_invalid")
    _text(title, 160)
    _text(introduction, 4000, optional=True)
    request_key = cases._uuid(request_key)
    with scope(extra_case_ids=[case_id]) as guard:
        actor, case = guard.actor(provider, subject_id, case_id)
        cases._verify(case)
        cases._versions(case, expected_revision, expected_evidence_version)
        guard.permit(provider, actor, case, "EDIT", kind)
        pins = [guard.source.selection(value) for value in members]
        for pin in pins:
            guard.member(pin, provider, actor)
        payload = dict(title=title, introduction=introduction, members=pins, featured=featured)
        validate_payload(kind, payload)
        previous = (
            CollectionRevision.objects.select_related("series__case")
            .filter(request_key=request_key)
            .first()
        )
        if previous is not None:
            if (
                previous.series.case_id != case.pk
                or previous.series.kind != kind
                or previous.payload != payload
                or previous.number != expected_version + 1
                or (series_id and str(previous.series_id) != str(cases._uuid(series_id)))
                or (previous.provider_id, previous.subject_id, previous.auth_epoch)
                != (provider.provider_id, actor.subject_id, actor.auth_epoch)
                or str(previous.parent_id or "") != str(parent_id or "")
            ):
                raise cases.CaseConflict("collection_request_conflict")
            return _staff_row(previous, guard, provider, actor)
        if series_id:
            series = CollectionSeries.objects.filter(
                pk=cases._uuid(series_id), case=case, kind=kind
            ).first()
            if series is None:
                raise cases.CaseConflict("collection_series_unavailable")
            latest = series.revisions.order_by("-number").first()
            if latest is None or latest.number != expected_version:
                raise cases.CaseConflict("collection_version_conflict")
        else:
            if expected_version != 0 or CollectionSeries.objects.filter(case=case).count() >= 32:
                raise cases.CaseConflict("collection_creation_bound")
            series = CollectionSeries(case=case, kind=kind)
        parent = _parent(
            guard, provider, actor, parent_id=parent_id, series_id=series.pk, kind=kind
        )
        if series._state.adding:
            series.save()
        record = CollectionRevision(
            series=series,
            number=expected_version + 1,
            case_revision=case.revision,
            evidence_version=case.evidence_version,
            parent=parent,
            payload=payload,
            request_key=request_key,
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
        )
        record.sha256 = fingerprint(record)
        record.save()
        return _staff_row(record, guard, provider, actor)


@mutation_service
def act(
    *,
    case_id,
    subject_id,
    provider,
    revision_id,
    action,
    expected_actions,
    expected_revision,
    expected_evidence_version,
    request_key,
    note,
    confirmed,
    minutes=0,
    related_id="",
    synthetic_fixtures_only=False,
):
    enabled()
    cases._guard(synthetic_fixtures_only)
    if (
        confirmed is not True
        or action not in {"REVIEW", "APPROVE", "RELEASE", "REVOKE", "WITHDRAW"}
        or type(expected_actions) is not int
        or not 0 <= expected_actions < 256
    ):
        raise cases.CaseConflict("collection_confirmation_required")
    _text(note, 2000, optional=action == "RELEASE")
    if (
        type(minutes) is not int
        or (action == "RELEASE" and minutes not in {5, 15, 30, 60})
        or (action != "RELEASE" and minutes != 0)
    ):
        raise cases.CaseConflict("collection_lease_bound")
    if action != "REVOKE" and related_id:
        raise cases.CaseConflict("collection_related_action_invalid")
    request_key = cases._uuid(request_key)
    with scope(extra_case_ids=[case_id]) as guard:
        actor, case = guard.actor(provider, subject_id, case_id)
        cases._verify(case)
        cases._versions(case, expected_revision, expected_evidence_version)
        record = current(revision_id)
        if record.series.case_id != case.pk:
            raise cases.CaseConflict("collection_revision_unavailable")
        _record_permission(
            guard, provider, actor, record, "WITHDRAW" if action == "REVOKE" else action
        )
        events, stage, approval, lease = verify(record)
        old = CollectionAction.objects.filter(request_key=request_key).first()
        if old is not None:
            if (
                old.revision_id != record.pk
                or old.action != action
                or old.note != note
                or old.requested_minutes != minutes
                or str(old.related_id or "") != str(related_id or "")
                or (old.provider_id, old.subject_id, old.auth_epoch)
                != (provider.provider_id, actor.subject_id, actor.auth_epoch)
            ):
                raise cases.CaseConflict("collection_request_conflict")
            return _staff_row(record, guard, provider, actor)
        if len(events) != expected_actions or stage == "WITHDRAWN":
            raise cases.CaseConflict("collection_action_conflict")
        if action not in {"WITHDRAW", "REVOKE"}:
            for pin in record.payload["members"]:
                guard.member(pin, provider, actor)
            _parent(
                guard,
                provider,
                actor,
                parent_id=record.parent_id,
                series_id=record.series_id,
                kind=record.series.kind,
            )
        identity = provider.provider_id, actor.subject_id
        creator = record.provider_id, record.subject_id
        if action == "REVIEW" and (stage != "DRAFT" or identity == creator):
            raise cases.CaseConflict("independent_collection_review_required")
        reviewer = next((event for event in events if event.action == "REVIEW"), None)
        if action == "APPROVE" and (
            stage != "REVIEWED"
            or reviewer is None
            or identity in {creator, (reviewer.provider_id, reviewer.subject_id)}
        ):
            raise cases.CaseConflict("independent_collection_approval_required")
        if action in {"RELEASE", "REVOKE"} and (stage != "APPROVED" or approval is None):
            raise cases.CaseConflict("collection_approval_required")
        related = None
        if action == "REVOKE":
            related = next(
                (
                    event
                    for event in events
                    if str(event.pk) == str(related_id) and event.action == "RELEASE"
                ),
                None,
            )
            if related is None or any(event.related_id == related.pk for event in events):
                raise cases.CaseConflict("collection_exact_lease_required")
        expires_at = None
        if action == "RELEASE":
            approving_actor, approving_case = guard.actor(
                guard.directory, approval.subject_id, record.series.case_id
            )
            if (
                guard.directory.provider_id != approval.provider_id
                or approving_actor.auth_epoch != approval.auth_epoch
            ):
                raise cases.CaseConflict("collection_approval_identity_changed")
            guard.permit(
                guard.directory,
                approving_actor,
                approving_case,
                "APPROVE",
                record.series.kind,
                record.pk,
                record.sha256,
            )
            for pin in record.payload["members"]:
                guard.member(pin, guard.directory, approving_actor)
            expires_at = min(
                [
                    timezone.now() + timedelta(minutes=minutes),
                    *guard.source.deadlines,
                    *guard.deadlines,
                ]
            )
            if expires_at <= timezone.now():
                raise cases.CaseConflict("collection_source_expired")
        CollectionAction.objects.create(
            revision=record,
            sequence=len(events) + 1,
            action=action,
            request_key=request_key,
            note=note,
            content_sha256=record.sha256,
            expires_at=expires_at,
            requested_minutes=minutes,
            related=related,
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
        )
        return _staff_row(record, guard, provider, actor)


@mutation_service
def reorder(
    *,
    case_id,
    subject_id,
    provider,
    revision_id,
    index,
    direction,
    expected_version,
    expected_revision,
    expected_evidence_version,
    request_key,
    synthetic_fixtures_only=False,
):
    cases._guard(synthetic_fixtures_only)
    with scope(extra_case_ids=[case_id]) as guard:
        actor, _ = guard.actor(provider, subject_id, case_id)
        record = current(revision_id)
        if record.series.case_id != cases._uuid(case_id) or record.number != expected_version:
            raise cases.CaseConflict("collection_version_conflict")
        _record_permission(guard, provider, actor, record, "READ")
        members = deepcopy(record.payload["members"])
        if (
            type(index) is not int
            or direction not in {"UP", "DOWN"}
            or not 0 <= index < len(members)
        ):
            raise cases.CaseConflict("collection_reorder_invalid")
        target = index + (-1 if direction == "UP" else 1)
        if not 0 <= target < len(members):
            raise cases.CaseConflict("collection_reorder_invalid")
        members[index], members[target] = members[target], members[index]
        return save(
            case_id=case_id,
            subject_id=subject_id,
            provider=provider,
            kind=record.series.kind,
            title=record.payload["title"],
            introduction=record.payload["introduction"],
            members=[sources.selection(pin) for pin in members],
            featured=record.payload["featured"],
            expected_version=expected_version,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
            request_key=request_key,
            series_id=str(record.series_id),
            parent_id=str(record.parent_id or ""),
            synthetic_fixtures_only=synthetic_fixtures_only,
        )


@mutation_context
@privacy.public_contextual
@contextmanager
def public_projection(*, search=False):
    try:
        if type(search) is not bool:
            raise preview.PreviewUnavailable()
        with scope(freeze_history=True) as guard:
            rows = available(guard, public=True, search=search)
            result = {}
            for identifier, item in rows.items():
                row = item["record"]
                result[identifier] = {
                    "id": str(row.series.public_id),
                    "kind": row.series.kind,
                    "kind_label": KINDS[row.series.kind],
                    "title": row.payload["title"],
                    "introduction": row.payload["introduction"],
                    "featured": row.payload["featured"],
                    "version": row.number,
                    "updated_at": row.created_at,
                    "members": item["cards"],
                    "url": f"/library-preview/collections/items/{row.series.public_id}/",
                    "parent": None,
                }
            for identifier, item in rows.items():
                parent_id = item["record"].parent_id
                if parent_id:
                    parent = result[str(parent_id)]
                    result[identifier]["parent"] = {
                        key: parent[key] for key in ("id", "title", "url")
                    }
            # No internal revision/member/case identifiers leave this projection.
            yield list(result.values())
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
