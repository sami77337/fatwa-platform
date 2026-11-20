"""One coherent anonymous projection under exact source grants and release leases."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.case_citations.services import _projection_expiry_guard
from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.platform_recovery.integration import mutation_context

from . import scholarly, services
from .models import PublicAction, PublicRevision


def _history_state(case_ids):
    return (
        list(PublicRevision.objects.filter(series__case_id__in=case_ids).order_by("pk").values()),
        list(
            PublicAction.objects.filter(revision__series__case_id__in=case_ids)
            .order_by("pk")
            .values()
        ),
    )


def _grant_actor(event, record, directory):
    if directory is None or directory.provider_id != event.provider_id:
        raise preview.PreviewUnavailable()
    case = record.series.case
    actor = cases._identity(directory, event.subject_id, case)
    if actor.auth_epoch != event.auth_epoch:
        raise preview.PreviewUnavailable()
    services._permit(
        actor, directory, case, event.action, record.series.kind, record.series.language
    )
    return actor


def _dependencies(record):
    value = record.payload
    result = list(value.get("topic_ids", []))
    if value.get("parent_id"):
        result.append(value["parent_id"])
    if value.get("scholar_id"):
        result.append(value["scholar_id"])
    result.extend(value.get("scholar_ids", []))
    return result


def _base(record):
    return {
        "id": str(record.series_id),
        "version": record.number,
        "publication_id": str(record.publication_id),
        "updated_at": record.created_at,
        "kind": record.series.kind,
        "language": record.series.language or "ar",
    }


class Snapshot:
    """Templates receive only explicit display DTOs, never these internal models."""

    def __init__(self, sources, records, related):
        self.sources = sources
        self.records = records
        self.scholars, self.topics, self.presentations, self.lessons = {}, {}, {}, {}
        for key, record in records.items():
            value = record.payload
            row = _base(record)
            if record.series.kind == "SCHOLAR":
                self.scholars[key] = {**row, "name": value["name"], "bio": value["bio"]}
            elif record.series.kind == "TOPIC":
                self.topics[key] = {
                    **row,
                    "title": value["title"],
                    "introduction": value["introduction"],
                }
        for key, row in self.topics.items():
            parent = records[key].payload["parent_id"]
            row["parent"] = self.topics.get(parent)
        for key, record in records.items():
            value = record.payload
            row = _base(record)
            if record.series.kind == "PRESENTATION":
                source = sources[str(record.publication_id)][1]
                self.presentations[key] = {
                    **row,
                    "title": value["title"],
                    "question": value["question"],
                    "description": value["description"],
                    "body": source["body"] if record.series.language == "ar" else value["body"],
                    "scholar": self.scholars.get(value["scholar_id"]),
                    "topics": [self.topics[item] for item in value["topic_ids"]],
                    "source_version": source["number"],
                    "references": source["references"],
                    "related": related.get(key, []),
                }
            elif record.series.kind == "LESSON":
                self.lessons[key] = {
                    **row,
                    "title": value["title"],
                    "summary": value["summary"],
                    "scholars": [self.scholars[item] for item in value["scholar_ids"]],
                    "topics": [self.topics[item] for item in value["topic_ids"]],
                    "lesson_version": value["lesson_version"],
                }

    def presentation(self, publication_id, language="ar"):
        return next(
            (
                row
                for row in self.presentations.values()
                if row["publication_id"] == str(publication_id) and row["language"] == language
            ),
            None,
        )

    def publication_cards(self):
        result = []
        for identifier, (source, values) in self.sources.items():
            enriched = self.presentation(identifier)
            result.append(
                {
                    "publication_id": identifier,
                    "title": values["title"],
                    "version": values["number"],
                    "category": values["category"],
                    "presentation": enriched,
                }
            )
        return result

    def scholar(self, series_id):
        key, row = next(
            ((key, row) for key, row in self.scholars.items() if row["id"] == str(series_id)),
            (None, None),
        )
        if row is None:
            raise preview.PreviewUnavailable()
        record = self.records[key]
        identity = record.series.author_provider, record.series.author_subject
        publications = []
        for card in self.publication_cards():
            source = self.sources[card["publication_id"]][0]
            if (source.answer.provider_id, source.answer.subject_id) == identity:
                publications.append(card)
        lessons = [lesson for lesson in self.lessons.values() if row in lesson["scholars"]]
        return {**row, "publications": publications, "lessons": lessons}

    def topic(self, series_id):
        key, row = next(
            ((key, row) for key, row in self.topics.items() if row["id"] == str(series_id)),
            (None, None),
        )
        if row is None:
            raise preview.PreviewUnavailable()
        descendant_ids = {row["id"]}
        for _ in range(5):
            descendant_ids.update(
                item["id"]
                for item in self.topics.values()
                if item["parent"] and item["parent"]["id"] in descendant_ids
            )
        publications = [
            card
            for card in self.publication_cards()
            if card["presentation"]
            and any(topic["id"] in descendant_ids for topic in card["presentation"]["topics"])
        ]
        lessons = [
            lesson
            for lesson in self.lessons.values()
            if any(topic["id"] in descendant_ids for topic in lesson["topics"])
        ]
        references, seen = [], set()
        for card in publications:
            for ref in self.sources[card["publication_id"]][1]["references"]:
                identity = card["publication_id"], ref["position"]
                if identity not in seen:
                    seen.add(identity)
                    references.append({**ref, "publication_id": card["publication_id"]})
        return {
            **row,
            "publications": publications,
            "lessons": lessons,
            "references": references,
            "children": [
                item
                for item in self.topics.values()
                if item["parent"] and item["parent"]["id"] == row["id"]
            ],
        }

    def lesson(self, series_id):
        row = next((row for row in self.lessons.values() if row["id"] == str(series_id)), None)
        if row is None:
            raise preview.PreviewUnavailable()
        return row


@mutation_context
@contextmanager
def projection():
    """Hold through the caller's final HTML/XML render, not just its data reads."""
    try:
        services.enabled()
        selected = preview._start()
        authority = services._epoch()
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        configured_languages = services.languages()
        source_configuration = services._source_configuration()
        actors, deadlines = [], [selected.valid_until]
        with (
            synthetic_queue_atomic(),
            transaction.atomic(),
            preview._media_boundary(),
            _projection_expiry_guard(),
            ExitStack() as stack,
        ):
            case_ids = list(
                PublicationEdition.objects.filter(
                    pk__in=[g.publication_id for g in selected.publications]
                )
                .order_by("case_id")
                .values_list("case_id", flat=True)
                .distinct()
            )
            scholarly_boundary = stack.enter_context(scholarly.scope(case_ids=case_ids))
            if scholarly_boundary:
                case_ids = list(scholarly_boundary.locked)
            list(Case.objects.filter(pk__in=case_ids).order_by("pk").select_for_update())
            source_state = services._canonical(case_ids)
            history_state = _history_state(case_ids)
            sources = {}
            for grant in selected.publications:
                try:
                    with preview._current(selected, grant.publication_id) as edition:
                        values = preview._projection(selected, edition)
                    sources[str(edition.pk)] = edition, values
                except preview.PreviewUnavailable:
                    continue
            exact_source_views = {
                identifier: deepcopy(values) for identifier, (_, values) in sources.items()
            }
            available = {}
            candidates = (
                PublicRevision.objects.filter(publication_id__in=sources)
                .select_related("series__case", "publication__decision")
                .order_by("series_id", "-number")
            )
            seen = set()
            for record in candidates:
                if record.series_id in seen:
                    continue
                seen.add(record.series_id)
                if record.series.revisions.order_by("-number").first().pk != record.pk:
                    continue
                _, stage, approval, lease = services._verify(record)
                if (
                    stage != "APPROVED"
                    or lease is None
                    or (
                        record.series.kind == "PRESENTATION"
                        and record.series.language not in configured_languages
                    )
                ):
                    continue
                for event in (approval, lease):
                    identity = _grant_actor(event, record, directory)
                    actors.append((identity, event, record))
                    deadlines.append(identity.valid_until)
                deadlines.append(lease.expires_at)
                available[str(record.pk)] = record
            # Missing/withdrawn profiles, topic ancestors and exact associations
            # cannot survive through another released card or its count.
            for _ in range(65):
                removed = {
                    key
                    for key, row in available.items()
                    if any(dependency not in available for dependency in _dependencies(row))
                }
                if not removed:
                    break
                for key in removed:
                    del available[key]
            related = {}
            for record in available.values():
                # A normal superseded dependency is omitted above; a current
                # dependency still needs its exact source/teacher permissions.
                lease = services._verify(record)[3]
                actor = _grant_actor(lease, record, directory)
                services._dependencies(
                    record, actor=actor, provider=directory, case=record.series.case
                )
                if record.series.kind == "PRESENTATION":
                    related[str(record.pk)] = scholarly.related_publications(
                        record, sources, actor=actor, provider=directory
                    )
            snapshot = Snapshot(sources, available, related)
            yield snapshot
            # All permission callbacks precede the final source/history snapshot.
            for identity, event, record in actors:
                current = _grant_actor(event, record, directory)
                if services._identity_tuple(current) != services._identity_tuple(identity):
                    raise preview.PreviewUnavailable()
            if scholarly_boundary:
                scholarly_boundary.permission_callbacks()
            # Re-resolve exact citation/annotation material after every permission
            # callback. Compare pre-render values, not template-mutated DTOs.
            for identifier, expected in exact_source_views.items():
                with preview._current(selected, identifier) as current_source:
                    if preview._projection(selected, current_source) != expected:
                        raise preview.PreviewUnavailable()
            if scholarly_boundary:
                scholarly_boundary.identity_callbacks()
            # Resolve public release identities after all scholarly callbacks.
            for identity, event, record in actors:
                fresh = cases._identity(directory, event.subject_id, record.series.case)
                if services._identity_tuple(fresh) != services._identity_tuple(identity):
                    raise preview.PreviewUnavailable()
            if scholarly_boundary:
                scholarly_boundary.final_pins()
            if (
                getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not directory
                or not services._same_epoch(authority)
                or services._source_configuration() != source_configuration
            ):
                raise preview.PreviewUnavailable()
            services.enabled()
            if services.languages() != configured_languages:
                raise preview.PreviewUnavailable()
            preview._recheck(selected)
            if (
                services._canonical(case_ids) != source_state
                or _history_state(case_ids) != history_state
            ):
                raise preview.PreviewUnavailable()
            if any(value <= timezone.now() for value in deadlines):
                raise preview.PreviewUnavailable()
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
