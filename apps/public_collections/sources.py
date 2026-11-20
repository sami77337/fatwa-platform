"""Compose current public readers under one graph-first, sorted case boundary.

The internal pins and case map are never template context. Nested readers retain
their own grants; this outer before/after fingerprint catches callbacks in a
later reader withdrawing an earlier reader after that reader's final check.
"""

from contextlib import ExitStack, contextmanager
from copy import deepcopy

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.public_knowledge import public as knowledge_public
from apps.public_knowledge import scholarly
from apps.public_knowledge import services as knowledge

KINDS = {"PUBLICATION", "PRESENTATION", "SCHOLAR", "LESSON", "LIBRARY"}
LABELS = {
    "PUBLICATION": "فتوى",
    "PRESENTATION": "فتوى محررة",
    "SCHOLAR": "عالم",
    "LESSON": "درس",
    "LIBRARY": "مادة مكتبية",
}


def library_api():
    enabled = getattr(settings, "FATWA_RESEARCH_LIBRARY_ENABLED", False)
    if (
        enabled is not True
        or getattr(settings, "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED", False) is not True
    ):
        return None
    if not apps.is_installed("apps.research_library"):
        raise cases.CaseConflict("collection_library_unavailable")
    from apps.research_library import public, services

    return services, public


def case_ids():
    """No identity or permission callbacks; caller already owns the graph lock."""
    from .models import CollectionSeries

    policy = preview.policy()
    result = set(
        PublicationEdition.objects.filter(
            pk__in=[row.publication_id for row in policy.publications]
        ).values_list("case_id", flat=True)
    )
    # Include all collection owners, including unreleased empty-set phantoms.
    result.update(CollectionSeries.objects.values_list("case_id", flat=True))
    library = library_api()
    if library is not None:
        result.update(cases._uuid(value) for value in library[0].public_case_ids())
    if len(result) > 192:
        raise cases.CaseConflict("collection_scope_bound")
    return result


def fingerprint(locked):
    """Pure row/config/atomic-epoch reads only. Does not invoke permissions."""
    authority, epoch = knowledge._epoch()
    library = library_api()
    return (
        knowledge._canonical(locked),
        knowledge_public._history_state(locked),
        knowledge._source_configuration(),
        knowledge.languages(),
        id(authority),
        epoch,
        id(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
        id(getattr(settings, "FATWA_LIBRARY_PREVIEW_POLICY", None)),
        getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_ENABLED", None),
        getattr(settings, "FATWA_RESEARCH_LIBRARY_ENABLED", None),
        getattr(settings, "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED", None),
        None if library is None else library[0].public_fingerprint(),
    )


class Snapshot:
    def __init__(self, knowledge_snapshot, library_snapshot, locked):
        self.locked = locked
        self.members = {}
        self.deadlines = [preview.policy().valid_until]
        for identifier, (source, values) in knowledge_snapshot.sources.items():
            self._add(
                "PUBLICATION",
                identifier,
                source.content_sha256,
                source.number,
                source.case_id,
                values["title"],
                f"/library-preview/knowledge/publications/{identifier}/ar/",
                "ar",
            )
        tables = {
            "PRESENTATION": knowledge_snapshot.presentations,
            "SCHOLAR": knowledge_snapshot.scholars,
            "LESSON": knowledge_snapshot.lessons,
        }
        for kind, rows in tables.items():
            for identifier, dto in rows.items():
                record = knowledge_snapshot.records[identifier]
                if kind == "PRESENTATION":
                    url = f"/library-preview/knowledge/publications/{dto['publication_id']}/{dto['language']}/"
                else:
                    route = "scholars" if kind == "SCHOLAR" else "lessons"
                    url = f"/library-preview/knowledge/{route}/{dto['id']}/"
                self._add(
                    kind,
                    identifier,
                    record.sha256,
                    record.number,
                    record.series.case_id,
                    dto.get("title", dto.get("name")),
                    url,
                    dto["language"],
                )
                _, _, approval, lease = knowledge._verify(record)
                if lease is not None:
                    self.deadlines.append(lease.expires_at)
                directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
                for event in (approval, lease):
                    if event is not None:
                        actor = cases._identity(directory, event.subject_id, record.series.case)
                        self.deadlines.append(actor.valid_until)
        if library_snapshot is not None:
            self.deadlines.extend(library_snapshot.deadlines)
            for identifier, dto in library_snapshot.records.items():
                self._add(
                    "LIBRARY",
                    identifier,
                    dto["digest"],
                    dto["number"],
                    library_snapshot.case_ids[identifier],
                    dto["title"],
                    dto["url"],
                    dto["language"],
                )

    def _add(self, kind, identifier, digest, number, case_id, title, url, language):
        key = (kind, str(identifier))
        self.members[key] = {
            "pin": {
                "kind": kind,
                "id": str(identifier),
                "sha256": digest,
                "number": number,
                "case_id": str(case_id),
            },
            "card": {
                "kind": kind,
                "label": LABELS[kind],
                "title": title,
                "url": url,
                "version": number,
                "language": language,
            },
        }

    def read(self, pin):
        row = self.members.get((pin["kind"], pin["id"]))
        if row is None or row["pin"] != pin:
            raise cases.CaseConflict("collection_member_unavailable")
        return deepcopy(row["card"])

    def selection(self, value):
        if type(value) is not str or len(value) > 160:
            raise cases.CaseConflict("collection_selection_invalid")
        parts = value.split("|")
        if len(parts) != 3:
            raise cases.CaseConflict("collection_selection_invalid")
        kind, identifier, digest = parts
        row = self.members.get((kind, str(cases._uuid(identifier))))
        if row is None or row["pin"]["sha256"] != digest:
            raise cases.CaseConflict("collection_selection_unavailable")
        return deepcopy(row["pin"])


def selection(pin):
    return "|".join((pin["kind"], pin["id"], pin["sha256"]))


@contextmanager
def _boundary(*, extra_case_ids=()):
    with synthetic_queue_atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        selected = case_ids() | {cases._uuid(value) for value in extra_case_ids}
        # Scholarly closure includes both relation endpoints and every lesson owner.
        if scholarly.active():
            for _ in range(193):
                expanded = scholarly._closure(selected)
                if expanded == selected:
                    break
                selected = expanded
                if len(selected) > 192:
                    raise cases.CaseConflict("collection_scope_bound")
            else:
                raise cases.CaseConflict("collection_scope_bound")
        if len(selected) > 192:
            raise cases.CaseConflict("collection_scope_bound")
        locked = {
            row.pk: row
            for row in Case.objects.filter(pk__in=selected).order_by("pk").select_for_update()
        }
        with scholarly.scope(case_ids=selected) as scholarly_boundary:
            before = fingerprint(locked)
            with ExitStack() as stack:
                pk = stack.enter_context(knowledge_public.projection())
                library = library_api()
                lib = (
                    None if library is None else stack.enter_context(library[1].public_projection())
                )
                snapshot = Snapshot(pk, lib, locked)
                yield snapshot
            if scholarly_boundary:
                scholarly_boundary.permission_callbacks()
                scholarly_boundary.identity_callbacks()
                scholarly_boundary.final_pins()
            if lib is not None:
                lib.verify_source_pins()
            if fingerprint(locked) != before:
                raise cases.CaseConflict("collection_source_projection_changed")
            if any(deadline <= timezone.now() for deadline in snapshot.deadlines):
                raise cases.CaseConflict("collection_source_expired")


@contextmanager
def boundary(*, extra_case_ids=()):
    try:
        with _boundary(extra_case_ids=extra_case_ids) as snapshot:
            yield snapshot
    except preview.PreviewUnavailable as exc:
        # Public readers intentionally collapse both source denials and errors
        # thrown by their consumer. Preserve the staff service's closed contract.
        raise cases.CaseConflict("collection_source_unavailable") from exc
