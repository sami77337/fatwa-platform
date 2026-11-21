"""Exact public metadata and original lesson bytes under one retained source scope."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.precise_citations import integration as citations
from apps.public_knowledge import public as knowledge_public
from apps.public_knowledge import scholarly
from apps.public_knowledge import services as knowledge
from apps.research_library import public as library_public
from apps.research_library import services as library
from apps.scholarly_links import services as lessons
from apps.scholarly_links.models import LessonVersion, SeriesVersion

from .models import TeachingItem


def pin(row, *, case_id, digest=None):
    return {
        "id": str(row.pk),
        "sha256": digest or row.sha256,
        "number": row.number,
        "case_id": str(case_id),
    }


def _ids(extra):
    selected = preview.policy()
    result = {cases._uuid(value) for value in extra}
    result.update(
        PublicationEdition.objects.filter(
            pk__in=[grant.publication_id for grant in selected.publications]
        ).values_list("case_id", flat=True)
    )
    result.update(cases._uuid(value) for value in library.public_case_ids())
    result.update(TeachingItem.objects.values_list("case_id", flat=True))
    for _ in range(193):
        expanded = scholarly._closure(result)
        expanded = citations.dependency_case_ids(expanded)
        if expanded == result:
            break
        result = expanded
        if len(result) > 192:
            raise cases.CaseConflict("teaching_source_scope_bound")
    else:
        raise cases.CaseConflict("teaching_source_scope_bound")
    if len(result) > 192:
        raise cases.CaseConflict("teaching_source_scope_bound")
    return result


def fingerprint(locked):
    policy, epoch = knowledge._epoch()
    scholarly_policy, scholarly_epoch = scholarly._policy()
    library_policy = library.policy_snapshot()
    return (
        knowledge._canonical(locked),
        knowledge_public._history_state(locked),
        knowledge._source_configuration(),
        knowledge.languages(),
        id(policy),
        epoch,
        lessons.projection_fingerprint(locked),
        id(scholarly_policy),
        scholarly_epoch,
        id(library_policy[0]),
        library_policy[1:],
        library.public_fingerprint(),
        id(getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)),
        id(getattr(settings, "FATWA_LIBRARY_PREVIEW_POLICY", None)),
        library.identity_snapshot(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
        tuple(
            (type(value), value)
            for value in (
                getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", None),
                getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_ENABLED", None),
                getattr(settings, "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED", None),
                getattr(settings, "FATWA_SCHOLARLY_LINKS_ENABLED", None),
            )
        ),
    )


class Snapshot:
    def __init__(self, locked, pk, lib, scholarly_boundary, selected, before):
        self.locked, self.pk, self.lib = locked, pk, lib
        self.scholarly = scholarly_boundary
        self.selected = selected
        self.before = before
        self.parts = {}
        self.deadlines = [selected.valid_until, *lib.deadlines]

    def record(self, identifier, kind):
        row = self.pk.records.get(str(identifier))
        if row is None or row.series.kind != kind:
            raise cases.CaseConflict("teaching_public_metadata_unavailable")
        _, _, approval, lease = knowledge._verify(row)
        if lease is None:
            raise cases.CaseConflict("teaching_public_metadata_unavailable")
        self.deadlines.append(lease.expires_at)
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        for event in (approval, lease):
            actor = cases._identity(directory, event.subject_id, row.series.case)
            self.deadlines.append(actor.valid_until)
        return row

    def record_pin(self, identifier, kind):
        row = self.record(identifier, kind)
        return pin(row, case_id=row.series.case_id)

    def library_pin(self, identifier):
        try:
            dto = self.lib.read(identifier)
        except preview.PreviewUnavailable as exc:
            raise cases.CaseConflict("teaching_material_unavailable") from exc
        return {
            "id": str(identifier),
            "sha256": dto["digest"],
            "number": dto["number"],
            "case_id": self.lib.case_ids[str(identifier)],
        }

    def series(self, identifier, *, provider, actor):
        row = (
            SeriesVersion.objects.select_related("series")
            .filter(pk=cases._uuid(identifier))
            .first()
        )
        if row is None or row.series.case_id not in self.locked:
            raise cases.CaseConflict("teaching_series_unavailable")
        lessons._verified(row)
        guard = self.scholarly.guard(actor, provider, [row.series.case_id])
        owner = self.locked[row.series.case_id]
        guard.permit(owner, owner, "READ_LESSON", "SERIES", row.pk, row.sha256)
        return row

    def lesson(self, metadata_id, *, provider, actor, content=False):
        record = self.record(metadata_id, "LESSON")
        candidate = scholarly.verify_lesson(record, actor=actor, provider=provider)
        row = LessonVersion.objects.select_related(
            "lesson__series", "series_version", "source_part__manifest__answer__decision"
        ).get(pk=candidate["lesson_version_id"])
        if row.source_part_id is None or row.source_part.kind != "AUDIO":
            raise cases.CaseConflict("teaching_original_recording_required")
        decision = getattr(row.source_part.manifest.answer, "decision", None)
        if decision is None or decision.action != "APPROVE":
            raise cases.CaseConflict("teaching_original_review_required")
        if content:
            owner = self.locked[row.lesson.series.case_id]
            guard = self.scholarly.guard(actor, provider, [owner.pk])
            guard.permit(
                owner, owner, "READ_MEDIA", "LESSON", row.source_part_id, row.source_part.sha256
            )
            raw = media.raw_for_part(row.source_part)
            if (
                sha256(raw).hexdigest() != row.source_part.sha256
                or len(raw) != row.source_part.size
            ):
                raise cases.CaseConflict("teaching_original_changed")
            self.parts[str(row.source_part_id)] = (row.source_part, deepcopy(row.source_snapshot))
        return record, row

    def lesson_pins(self, metadata_id, *, provider, actor, content=False):
        record, row = self.lesson(metadata_id, provider=provider, actor=actor, content=content)
        return (
            {
                "metadata": pin(record, case_id=record.series.case_id),
                "lesson": pin(row, case_id=row.lesson.series.case_id),
                "series": pin(row.series_version, case_id=row.lesson.series.case_id),
                "part": deepcopy(row.source_snapshot),
            },
            record,
            row,
        )

    def verify_bytes(self):
        self.lib.verify_source_pins()
        for part, expected in self.parts.values():
            raw = media.raw_for_part(part)
            if len(raw) != expected["size"] or sha256(raw).hexdigest() != expected["sha256"]:
                raise cases.CaseConflict("teaching_original_changed")

    def pure_parts(self):
        for identifier, (_, expected) in self.parts.items():
            part = AnswerPart.objects.select_related("manifest__answer").get(pk=identifier)
            if lessons._source_snapshot(part) != expected:
                raise cases.CaseConflict("teaching_original_pin_changed")
        preview._recheck(self.selected)
        if any(deadline <= timezone.now() for deadline in self.deadlines):
            raise cases.CaseConflict("teaching_source_expired")

    def pure(self):
        self.pure_parts()
        if fingerprint(self.locked) != self.before:
            raise cases.CaseConflict("teaching_source_projection_changed")


@contextmanager
def boundary(*, extra_case_ids=()):
    """All callbacks, then bytes, then pure state, including final citation exit."""
    snapshot = None
    operation_error = None
    try:
        selected = preview._start()
        if not scholarly.active():
            raise cases.CaseConflict("teaching_scholarly_source_required")
        with synthetic_queue_atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
            identifiers = citations.prelock_cases(_ids(extra_case_ids))
            locked = {
                row.pk: row
                for row in Case.objects.filter(pk__in=identifiers)
                .order_by("pk")
                .select_for_update()
            }
            with scholarly.scope(case_ids=identifiers) as scholarly_boundary:
                before = fingerprint(locked)
                with citations.answer_use_boundary():
                    with ExitStack() as stack:
                        pk = stack.enter_context(knowledge_public.projection())
                        lib = stack.enter_context(library_public.public_projection())
                        snapshot = Snapshot(locked, pk, lib, scholarly_boundary, selected, before)
                        try:
                            yield snapshot
                        except cases.CaseConflict as exc:
                            # Lower public-source scopes deliberately translate
                            # conflicts to anonymous not-found responses. Keep a
                            # staff operation's original conflict for its caller;
                            # the public adapter still maps every conflict to404.
                            operation_error = exc
                            raise
                    scholarly_boundary.permission_callbacks()
                    scholarly_boundary.identity_callbacks()
                    snapshot.verify_bytes()
                    scholarly_boundary.final_pins()
                    snapshot.pure_parts()
                    if fingerprint(locked) != before:
                        raise cases.CaseConflict("teaching_source_projection_changed")
                # A final exact-citation reader may call storage/rights adapters.
                # No byte or permission callback follows these last comparisons.
                scholarly_boundary.final_pins()
                snapshot.pure_parts()
                if fingerprint(locked) != before:
                    raise cases.CaseConflict("teaching_source_projection_changed")
    except preview.PreviewUnavailable as exc:
        if operation_error is not None:
            raise operation_error from exc
        raise cases.CaseConflict("teaching_public_source_unavailable") from exc
