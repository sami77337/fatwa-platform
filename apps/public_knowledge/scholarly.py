"""Exact private-to-public adapter; stored public leases are never staff grants.

The boundary owns graph/case locks until HTML/XML is rendered.  Permission
callbacks run before the final side-effect-free epoch, row and source-byte pins.
Only separately curated public strings and exact granted publication IDs leave
this module; private link notes, source paths and identity keys never do.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models import Q

from apps.casework import services as cases
from apps.casework.models import Case
from apps.mufti_review.identity import resolve_identity

_CURRENT = ContextVar("public_knowledge_scholarly_boundary", default=None)


def active():
    return (
        apps.is_installed("apps.scholarly_links")
        and getattr(settings, "FATWA_SCHOLARLY_LINKS_ENABLED", False) is True
    )


def _api():
    if not active():
        raise cases.CaseConflict("public_scholarly_integration_unavailable")
    from apps.scholarly_links import services

    services._enabled()
    return services


def _policy():
    api = _api()
    policy = getattr(settings, "FATWA_SCHOLARLY_LINKS_AUTHORITY", None)
    if not isinstance(policy, api.ScholarlyAuthority):
        raise cases.CaseConflict("public_scholarly_authority_required")
    try:
        epoch = policy.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("public_scholarly_epoch_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 128:
        raise cases.CaseConflict("public_scholarly_epoch_required")
    return policy, epoch


def _closure(case_ids):
    from apps.scholarly_links.models import CaseLessonLink, CaseRelation

    result = {cases._uuid(value) for value in case_ids}
    for source, target in CaseRelation.objects.filter(
        Q(source_case_id__in=result) | Q(target_case_id__in=result)
    ).values_list("source_case_id", "target_case_id"):
        result.update((source, target))
    result.update(
        CaseLessonLink.objects.filter(case_id__in=case_ids).values_list(
            "lesson_version__lesson__series__case_id", flat=True
        )
    )
    return result


class Boundary:
    def __init__(self, locked):
        self.locked = locked
        self.policy, self.epoch = _policy()
        self.fingerprint = _api().projection_fingerprint(locked)
        self.guards = {}
        self.identities = []

    def guard(self, actor, provider, case_ids):
        from .services import _identity_tuple

        key = (id(provider), actor.subject_id, actor.auth_epoch)
        if key not in self.guards:
            self.guards[key] = _api().ProjectionGuard(
                provider, actor, provider.provider_id, self.policy, self.epoch, []
            )
        for case_id in case_ids:
            case = self.locked.get(cases._uuid(case_id))
            if case is None:
                raise cases.CaseConflict("public_scholarly_scope_unavailable")
            fresh = cases._identity(provider, actor.subject_id, case)
            if _identity_tuple(fresh) != _identity_tuple(actor):
                raise cases.CaseConflict("public_scholarly_identity_changed")
            entry = (provider, actor, case)
            if entry not in self.identities:
                self.identities.append(entry)
        return self.guards[key]

    def permission_callbacks(self):
        for guard in self.guards.values():
            for arguments in guard.checks:
                try:
                    allowed = self.policy.permits(**arguments)
                except Exception as exc:
                    raise cases.CaseConflict("public_scholarly_authority_unavailable") from exc
                if allowed is not True:
                    raise cases.CaseConflict("public_scholarly_read_revoked")

    def identity_callbacks(self):
        from .services import _identity_tuple

        for provider, actor, case in self.identities:
            fresh = cases._identity(provider, actor.subject_id, case)
            if _identity_tuple(fresh) != _identity_tuple(actor):
                raise cases.CaseConflict("public_scholarly_identity_changed")

    def final_pins(self):
        from apps.answer_media.models import AnswerPart

        api = _api()
        # These byte/row reads and the required atomic epoch read make no policy
        # callbacks. A later callback therefore cannot revoke an earlier row.
        for guard in self.guards.values():
            if guard.provider.provider_id != guard.provider_id:
                raise cases.CaseConflict("public_scholarly_identity_changed")
            for part_id, expected in guard.part_pins.items():
                part = (
                    AnswerPart.objects.select_related("manifest__answer").filter(pk=part_id).first()
                )
                if part is None or api._source_snapshot(part) != expected:
                    raise cases.CaseConflict("public_lesson_source_changed")
        current_policy, current_epoch = _policy()
        if (
            api.projection_fingerprint(self.locked) != self.fingerprint
            or current_policy is not self.policy
            or current_epoch != self.epoch
        ):
            raise cases.CaseConflict("public_scholarly_projection_changed")


@contextmanager
def scope(*, case_ids=None, subject_id=None, provider=None):
    """Caller owns synthetic_queue_atomic; acquire graph before all case locks."""
    existing = _CURRENT.get()
    if existing is not None or not active():
        yield existing
        return
    if not connection.in_atomic_block:
        raise cases.CaseConflict("public_scholarly_transaction_required")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
    if subject_id is not None:
        actor = resolve_identity(provider, subject_id)
        identities = Case.objects.filter(public_ref__in=actor.case_keys).values_list(
            "pk", flat=True
        )
    else:
        identities = _closure(case_ids or ())
    from apps.precise_citations.integration import prelock_cases

    identities = prelock_cases(identities)
    locked = {
        row.pk: row
        for row in Case.objects.filter(pk__in=identities).order_by("pk").select_for_update()
    }
    boundary = Boundary(locked)
    token = _CURRENT.set(boundary)
    try:
        yield boundary
    finally:
        _CURRENT.reset(token)


def _boundary():
    selected = _CURRENT.get()
    if selected is None:
        raise cases.CaseConflict("public_scholarly_boundary_required")
    return selected


def _candidates(source):
    boundary = _boundary()
    case = boundary.locked.get(source.case_id)
    if case is None:
        raise cases.CaseConflict("public_scholarly_scope_unavailable")
    return _api().approved_candidates_for_locked_case(case=case, answer_id=source.answer_id)


def _relation(candidate, *, actor, provider):
    boundary = _boundary()
    guard = boundary.guard(
        actor, provider, [candidate["source_case_id"], candidate["target_case_id"]]
    )
    source = boundary.locked[cases._uuid(candidate["source_case_id"])]
    target = boundary.locked[cases._uuid(candidate["target_case_id"])]
    guard.permit(
        source, target, "READ_LINK", candidate["kind"], candidate["id"], candidate["sha256"]
    )
    if (
        str(source.approved_answer_id) != candidate["source_answer_id"]
        or str(target.approved_answer_id) != candidate["target_answer_id"]
    ):
        raise cases.CaseConflict("public_relation_answer_superseded")
    return guard


def verify_relations(record, *, actor, provider):
    selected = record.payload.get("relation_ids", [])
    if not selected:
        return []
    candidates = {row["id"]: row for row in _candidates(record.publication)["relations"]}
    result = []
    for identifier in selected:
        row = candidates.get(identifier)
        if row is None:
            raise cases.CaseConflict("public_relation_unavailable")
        _relation(row, actor=actor, provider=provider)
        result.append(row)
    return result


def _lesson(candidate, *, source, actor, provider):
    from apps.scholarly_links.models import LessonVersion

    boundary, api = _boundary(), _api()
    guard = boundary.guard(actor, provider, [source.case_id, candidate["owner_case_id"]])
    owner = boundary.locked[cases._uuid(candidate["owner_case_id"])]
    case = boundary.locked[source.case_id]
    guard.permit(case, owner, "READ_LINK", "LESSON", candidate["link_id"], candidate["link_sha256"])
    version = LessonVersion.objects.select_related(
        "lesson__series", "series_version", "category", "source_part__manifest__answer"
    ).get(pk=candidate["lesson_version_id"])
    # Metadata access is distinct from file access. Never emit a media URL or
    # call READ_MEDIA merely to publish reviewed, separately supplied metadata.
    api._verified(version)
    guard.permit(owner, owner, "READ_LESSON", "LESSON", version.pk, version.sha256)
    if version.source_part_id:
        snapshot = api._source_snapshot(version.source_part)
        if snapshot != version.source_snapshot:
            raise cases.CaseConflict("public_lesson_source_changed")
        guard.part_pins[str(version.source_part_id)] = snapshot
    return version


def verify_lesson(record, *, actor, provider):
    value = record.payload
    matching = [
        row
        for row in _candidates(record.publication)["lessons"]
        if (row["lesson_public_id"], row["lesson_version"], row["lesson_sha256"])
        == (value["lesson_public_id"], value["lesson_version"], value["lesson_sha256"])
    ]
    if not matching:
        raise cases.CaseConflict("public_lesson_unavailable")
    candidate = matching[0]
    _lesson(candidate, source=record.publication, actor=actor, provider=provider)
    from .models import PublicRevision

    teachers = {(row["provider_id"], row["subject_id"]) for row in candidate["teacher_keys"]}
    for identifier in value["scholar_ids"]:
        profile = PublicRevision.objects.select_related("series").get(pk=identifier)
        if (profile.series.author_provider, profile.series.author_subject) not in teachers:
            raise cases.CaseConflict("public_lesson_teacher_mismatch")
    return candidate


def choices(source, *, actor, provider):
    """Private native editor choices, after exact endpoint scope and READ checks."""
    if not active():
        return {"lesson_choices": [], "relation_choices": []}
    candidates = _candidates(source)
    lessons, relations = [], []
    for row in candidates["relations"]:
        try:
            _relation(row, actor=actor, provider=provider)
        except cases.CaseConflict:
            continue
        target_id = (
            row["target_case_id"] if row["direction"] == "OUTGOING" else row["source_case_id"]
        )
        target = _boundary().locked[cases._uuid(target_id)]
        labels = _api().KIND_LABELS if row["direction"] == "OUTGOING" else _api().INVERSE_LABELS
        relations.append(
            {"id": row["id"], "label": labels[row["kind"]], "case_ref": target.public_ref}
        )
    for row in candidates["lessons"]:
        try:
            version = _lesson(row, source=source, actor=actor, provider=provider)
        except cases.CaseConflict:
            continue
        lessons.append(
            {
                "choice": f"{row['lesson_public_id']}|{row['lesson_version']}|{row['lesson_sha256']}",
                "title": version.title,
            }
        )
    return {"lesson_choices": lessons, "relation_choices": relations}


def related_publications(record, visible_sources, *, actor, provider):
    if record is None or not record.payload.get("relation_ids"):
        return []
    result = []
    for row in verify_relations(record, actor=actor, provider=provider):
        target_case = (
            row["target_case_id"] if row["direction"] == "OUTGOING" else row["source_case_id"]
        )
        target_answer = (
            row["target_answer_id"] if row["direction"] == "OUTGOING" else row["source_answer_id"]
        )
        for identifier, (edition, _) in visible_sources.items():
            if str(edition.case_id) == target_case and str(edition.answer_id) == target_answer:
                labels = (
                    _api().KIND_LABELS if row["direction"] == "OUTGOING" else _api().INVERSE_LABELS
                )
                result.append({"publication_id": identifier, "label": labels[row["kind"]]})
    return result
