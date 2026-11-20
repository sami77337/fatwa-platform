"""Owner-private, case-scoped collections with exact-resource reauthorization.

Collection revisioning is independent from the canonical case: changing a note
does not change facts, approve an answer or grant access to another case/source.
"""

from contextlib import contextmanager
from dataclasses import asdict

from django.conf import settings
from django.db.models import F

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.delivery_queue import services as queue
from apps.platform_recovery.integration import mutation_service

from . import services
from .models import (
    ResearchCollection,
    ResearchCollectionEvent,
    ResearchItem,
)
from .reference_batch import policy_boundary
from .rights import Resource, require

MAX_COLLECTIONS = 20
MAX_ITEMS = 30
MAX_SEARCHES = 20
MAX_EVENTS = 256
SUPPORTED = {"REFERENCE", "TRANSCRIPT", "KNOWLEDGE"}
FILTER_KEYS = {"query", "kind", "edition_id", "printed_part", "printed_page"}
ZERO = "0" * 64


def enabled():
    services._enabled()
    if getattr(settings, "FATWA_RESEARCH_COLLECTIONS_ENABLED", False) is not True:
        raise cases.CaseConflict("research_collections_disabled")


def _text(value, limit, *, optional=False):
    if type(value) is not str or len(value) > limit:
        raise cases.CaseConflict("research_collection_text_invalid")
    cases._text(value, optional=optional)
    return value


def _resource(value):
    if type(value) is not dict or set(value) != set(Resource.__dataclass_fields__):
        raise cases.CaseConflict("research_collection_resource_invalid")
    resource = Resource(**value)
    if (
        any(type(v) is not str for k, v in value.items() if k != "edition_id")
        or resource.kind not in SUPPORTED
        or resource.edition_id is not None
        and type(resource.edition_id) is not int
    ):
        raise cases.CaseConflict("research_collection_resource_invalid")
    return resource


def _filters(value):
    if type(value) is not dict or set(value) not in (FILTER_KEYS, FILTER_KEYS | {"ranking"}):
        raise cases.CaseConflict("research_collection_filters_invalid")
    if type(value["kind"]) is not str or value["kind"] not in services.KINDS:
        raise cases.CaseConflict("research_collection_filters_invalid")
    _text(value["query"], 80, optional=True)
    _text(value["printed_part"], 100, optional=True)
    if any(ord(c) < 32 for c in value["printed_part"]):
        raise cases.CaseConflict("research_collection_filters_invalid")
    for key, maximum in (("edition_id", 2147483647), ("printed_page", 999999999)):
        v = value[key]
        if v is not None and (type(v) is not int or not 1 <= v <= maximum):
            raise cases.CaseConflict("research_collection_filters_invalid")
    if "ranking" in value and (
        value["ranking"] != "evaluated_titles" or value["kind"] != "REFERENCE"
    ):
        raise cases.CaseConflict("research_collection_filters_invalid")
    return dict(value)


def _snapshot(collection):
    return {
        "title": collection.title,
        "archived": collection.archived,
        "items": [
            [str(row.pk), row.resource, row.ordinal, row.note]
            for row in collection.items.order_by("ordinal")
        ],
        "searches": [
            [str(row.pk), row.title, row.filters]
            for row in collection.searches.order_by("created_at", "pk")
        ],
    }


def _event_data(event):
    return {
        name: str(getattr(event, name)) if name == "collection_id" else getattr(event, name)
        for name in (
            "collection_id",
            "revision",
            "action",
            "details",
            "subject_id",
            "provider_id",
            "auth_epoch",
            "case_revision",
            "evidence_version",
            "state_sha256",
            "previous_sha256",
        )
    }


def _verify(collection):
    events = list(collection.events.order_by("revision")[: MAX_EVENTS + 1])
    previous = ZERO
    for number, event in enumerate(events, 1):
        if (
            event.revision != number
            or event.previous_sha256 != previous
            or event.provider_id != collection.provider_id
            or event.subject_id != collection.subject_id
            or event.sha256 != services._digest(_event_data(event))
        ):
            raise cases.CaseConflict("research_collection_history_invalid")
        previous = event.sha256
    if (
        not events
        or len(events) != collection.revision
        or len(events) > MAX_EVENTS
        or events[-1].state_sha256 != services._digest(_snapshot(collection))
    ):
        raise cases.CaseConflict("research_collection_history_invalid")
    for row in collection.items.all():
        _resource(row.resource)
        if row.resource_sha256 != services._digest(row.resource):
            raise cases.CaseConflict("research_collection_resource_invalid")
    return previous


def _record(collection, case, actor, action, details, previous):
    if collection.revision >= MAX_EVENTS:
        raise cases.CaseConflict("research_collection_history_capacity")
    collection.revision += 1
    collection.save(update_fields=["title", "archived", "revision", "updated_at"])
    event = ResearchCollectionEvent(
        collection=collection,
        revision=collection.revision,
        action=action,
        details=details,
        provider_id=collection.provider_id,
        subject_id=actor.subject_id,
        auth_epoch=actor.auth_epoch,
        case_revision=case.revision,
        evidence_version=case.evidence_version,
        state_sha256=services._digest(_snapshot(collection)),
        previous_sha256=previous,
    )
    event.sha256 = services._digest(_event_data(event))
    event.save(force_insert=True)


@contextmanager
def _scope(
    *,
    case_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    expected_case_revision=None,
    expected_evidence_version=None,
):
    enabled()
    with (
        queue.synthetic_queue_atomic(),
        cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_case_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
    ):
        yield case, actor
        services._recheck(case, actor, provider)


def _owned(case, actor, provider):
    return ResearchCollection.objects.filter(
        case=case, provider_id=provider.provider_id, subject_id=actor.subject_id
    )


def _get(case, actor, provider, collection_id, expected_revision=None):
    collection = (
        _owned(case, actor, provider)
        .select_for_update()
        .filter(pk=cases._uuid(collection_id))
        .first()
    )
    if collection is None:
        raise cases.CaseConflict("research_collection_unavailable")
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision != collection.revision
    ):
        raise cases.CaseConflict("research_collection_changed")
    previous = _verify(collection)
    return collection, previous


def _pins(case, collection=None):
    result = dict(
        public_ref=case.public_ref, revision=case.revision, evidence_version=case.evidence_version
    )
    if collection is not None:
        result.update(
            id=str(collection.pk),
            collection_revision=collection.revision,
            title=collection.title,
            archived=collection.archived,
        )
    return result


def _resolved(case, actor, provider, resource):
    require(actor, provider, case, "DISCOVER", resource)
    opened = services.open_resource(
        case_id=case.pk,
        subject_id=actor.subject_id,
        provider=provider,
        resource=resource,
        synthetic_fixtures_only=True,
    )
    require(actor, provider, case, "DISCOVER", resource)
    return opened


def _title(resource, opened):
    if resource.kind == "REFERENCE":
        return opened["source"]["heading_title"]
    if resource.kind == "TRANSCRIPT":
        return "تفريغ مرتبط: " + opened["source_id"]
    return opened["title"]


@mutation_service
def list_collections(**common):
    with _scope(**common) as (case, actor):
        result = _pins(case)
        result["collections"] = []
        for collection in _owned(case, actor, common["provider"]).order_by("created_at", "pk"):
            _verify(collection)
            result["collections"].append(_pins(case, collection))
        return result


@mutation_service
def create_collection(*, title, expected_case_revision, expected_evidence_version, **common):
    title = _text(title, 160)
    cases._mutation_versions(expected_case_revision, expected_evidence_version)
    with _scope(
        **common,
        expected_case_revision=expected_case_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, actor):
        if _owned(case, actor, common["provider"]).count() >= MAX_COLLECTIONS:
            raise cases.CaseConflict("research_collection_capacity")
        collection = ResearchCollection.objects.create(
            case=case,
            provider_id=common["provider"].provider_id,
            subject_id=actor.subject_id,
            title=title,
        )
        _record(collection, case, actor, "CREATE", {}, ZERO)
        return _pins(case, collection)


@mutation_service
def read_collection(*, collection_id, **common):
    with (
        _scope(**common) as (case, actor),
        citations._projection_expiry_guard(),
        policy_boundary(),
    ):
        collection, _ = _get(case, actor, common["provider"], collection_id)
        result = _pins(case, collection)
        result["items"] = []
        permitted = []
        for row in collection.items.order_by("ordinal"):
            resource = _resource(row.resource)
            item = dict(id=str(row.pk), ordinal=row.ordinal, available=False)
            try:
                opened = _resolved(case, actor, common["provider"], resource)
            except cases.CaseConflict as exc:
                if str(exc) in {"research_rights_unavailable", "research_policy_changed"}:
                    raise
                # The saved slot remains removable. Hide title, pins and notes:
                # a research note can quote the now-revoked source.
            else:
                item.update(
                    available=True,
                    resource=asdict(resource),
                    note=row.note,
                    title=_title(resource, opened),
                    kind=resource.kind,
                )
                permitted.append(resource)
            result["items"].append(item)
        result["searches"] = [
            dict(id=str(row.pk), title=row.title, filters=_filters(row.filters))
            for row in collection.searches.order_by("created_at", "pk")
        ]
        # Collection-wide final checks: opening a later resource must not leave
        # an earlier result/quoted note authorized under a now-revoked grant.
        for resource in permitted:
            _resolved(case, actor, common["provider"], resource)
        return result


@mutation_service
def change_collection(
    *,
    collection_id,
    expected_revision,
    expected_case_revision,
    expected_evidence_version,
    action,
    title="",
    item_id=None,
    note="",
    resource=None,
    direction="",
    filters=None,
    search_id=None,
    **common,
):
    cases._mutation_versions(expected_case_revision, expected_evidence_version)
    if type(expected_revision) is not int or expected_revision < 1:
        raise cases.CaseConflict("research_collection_version_required")
    actions = {
        "RENAME",
        "ARCHIVE",
        "RESTORE",
        "ADD",
        "NOTE",
        "REMOVE",
        "MOVE",
        "SAVE_SEARCH",
        "REMOVE_SEARCH",
    }
    if type(action) is not str or action not in actions:
        raise cases.CaseConflict("research_collection_action_invalid")
    provider = common["provider"]
    with (
        _scope(
            **common,
            expected_case_revision=expected_case_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
        citations._projection_expiry_guard(),
        policy_boundary(),
    ):
        collection, previous = _get(case, actor, provider, collection_id, expected_revision)
        if collection.archived and action != "RESTORE":
            raise cases.CaseConflict("research_collection_archived")
        details = {}
        checked_resource = None
        if action == "RENAME":
            collection.title = _text(title, 160)
        elif action in {"ARCHIVE", "RESTORE"}:
            if collection.archived == (action == "ARCHIVE"):
                raise cases.CaseConflict("research_collection_action_invalid")
            collection.archived = action == "ARCHIVE"
        elif action == "ADD":
            if not isinstance(resource, Resource):
                raise cases.CaseConflict("research_collection_resource_invalid")
            checked_resource = _resource(asdict(resource))
            _resolved(case, actor, provider, checked_resource)
            note = _text(note, 2000, optional=True)
            digest = services._digest(asdict(resource))
            if collection.items.filter(resource_sha256=digest).exists():
                raise cases.CaseConflict("research_collection_duplicate")
            if collection.items.count() >= MAX_ITEMS:
                raise cases.CaseConflict("research_collection_item_capacity")
            row = collection.items.create(
                resource=asdict(resource),
                resource_sha256=digest,
                ordinal=collection.items.count() + 1,
                note=note,
            )
            details = {"item_id": str(row.pk), "resource_sha256": digest}
        elif action in {"NOTE", "REMOVE", "MOVE"}:
            row = collection.items.filter(pk=cases._uuid(item_id)).first()
            if row is None:
                raise cases.CaseConflict("research_collection_item_unavailable")
            details = {"item_id": str(row.pk)}
            if action == "NOTE":
                checked_resource = _resource(row.resource)
                _resolved(case, actor, provider, checked_resource)
                row.note = _text(note, 2000, optional=True)
                row.save(update_fields=["note"])
            else:
                rows = list(collection.items.order_by("ordinal"))
                if action == "REMOVE":
                    removed_id = row.pk
                    row.delete()
                    rows = [r for r in rows if r.pk != removed_id]
                else:
                    if direction not in {"up", "down"}:
                        raise cases.CaseConflict("research_collection_direction_invalid")
                    index = next(i for i, r in enumerate(rows) if r.pk == row.pk)
                    target = index + (-1 if direction == "up" else 1)
                    if not 0 <= target < len(rows):
                        raise cases.CaseConflict("research_collection_position_boundary")
                    rows[index], rows[target] = rows[target], rows[index]
                    details["direction"] = direction
                # Temporary disjoint positions preserve uniqueness throughout.
                collection.items.update(ordinal=F("ordinal") + MAX_ITEMS)
                for ordinal, item in enumerate(rows, 1):
                    ResearchItem.objects.filter(pk=item.pk).update(ordinal=ordinal)
        elif action == "SAVE_SEARCH":
            title = _text(title, 160)
            filters = _filters(filters)
            if collection.searches.count() >= MAX_SEARCHES:
                raise cases.CaseConflict("research_collection_search_capacity")
            row = collection.searches.create(title=title, filters=filters)
            details = {"search_id": str(row.pk)}
        elif action == "REMOVE_SEARCH":
            row = collection.searches.filter(pk=cases._uuid(search_id)).first()
            if row is None:
                raise cases.CaseConflict("research_collection_search_unavailable")
            details = {"search_id": str(row.pk)}
            row.delete()
        _record(collection, case, actor, action, details, previous)
        if checked_resource is not None:
            _resolved(case, actor, provider, checked_resource)
        return _pins(case, collection)


@mutation_service
def open_items(*, collection_id, item_ids, expected_revision, **common):
    if (
        type(item_ids) is not list
        or not 1 <= len(item_ids) <= 3
        or any(type(item_id) is not str for item_id in item_ids)
        or len(set(item_ids)) != len(item_ids)
        or type(expected_revision) is not int
        or expected_revision < 1
    ):
        raise cases.CaseConflict("research_collection_selection_invalid")
    with (
        _scope(**common) as (case, actor),
        citations._projection_expiry_guard(),
        policy_boundary(),
    ):
        collection, _ = _get(case, actor, common["provider"], collection_id, expected_revision)
        opened = []
        for item_id in item_ids:
            row = collection.items.filter(pk=cases._uuid(item_id)).first()
            if row is None:
                raise cases.CaseConflict("research_collection_item_unavailable")
            resource = _resource(row.resource)
            content = _resolved(case, actor, common["provider"], resource)
            opened.append(
                dict(
                    id=str(row.pk),
                    resource=asdict(resource),
                    kind=resource.kind,
                    title=_title(resource, content),
                    note=row.note,
                    opened=content,
                )
            )
        for item in opened:
            _resolved(case, actor, common["provider"], Resource(**item["resource"]))
        return {**_pins(case, collection), "opened": opened}


@mutation_service
def saved_search(*, collection_id, search_id, expected_revision, **common):
    """Return instructions, never cached results; caller explicitly reruns search."""
    if type(expected_revision) is not int or expected_revision < 1:
        raise cases.CaseConflict("research_collection_version_required")
    with _scope(**common) as (case, actor):
        collection, _ = _get(case, actor, common["provider"], collection_id, expected_revision)
        row = collection.searches.filter(pk=cases._uuid(search_id)).first()
        if row is None:
            raise cases.CaseConflict("research_collection_search_unavailable")
        return _filters(row.filters)
