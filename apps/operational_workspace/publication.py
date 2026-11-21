"""Actual organizer management of existing Mufti-prepared publication editions."""

from contextlib import contextmanager

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication import services as editorial
from apps.experimental_publication.authority import PublicationAuthority
from apps.experimental_publication.models import PublicationEdition

from . import answer_sources, identity
from .boundary import digest, scope

ACTION_MAP = {
    "READ": "READ_PUBLICATION_EDITION",
    "REVIEW": "REVIEW_PUBLICATION_EDITION",
    "APPROVE": "APPROVE_PUBLICATION_EDITION",
    "WITHDRAW": "WITHDRAW_PUBLICATION_EDITION",
}
SOURCE_SETTINGS = (
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED",
    "FATWA_CASE_CITATIONS_ENABLED",
    "FATWA_SOURCE_RIGHTS_ENFORCED",
    "FATWA_SOURCE_RIGHTS_ENABLED",
)


def resource(case, edition):
    return {
        "kind": "CASE_PUBLICATION_EDITION",
        "case_id": str(case.pk),
        "edition_id": str(edition.pk),
        "content_sha256": edition.content_sha256,
        "answer_id": str(edition.answer_id),
        "decision_id": str(edition.decision_id),
        "evidence_version": edition.evidence_version,
    }


def source_configuration():
    return tuple(
        (type(value), value)
        for value in (getattr(settings, name, None) for name in SOURCE_SETTINGS)
    )


def rights_state(case):
    if not apps.is_installed("apps.source_rights"):
        return None
    from apps.source_rights.models import (
        RightsAction,
        RightsRevision,
        SourceRegistration,
        SourceVersion,
    )

    registrations = SourceRegistration.objects.filter(case=case)
    return digest(
        [
            list(registrations.order_by("pk").values()),
            list(
                SourceVersion.objects.filter(sourceregistration__in=registrations)
                .order_by("pk")
                .values()
            ),
            list(RightsRevision.objects.filter(case=case).order_by("pk").values()),
            list(RightsAction.objects.filter(revision__case=case).order_by("pk").values()),
        ]
    )


class PublicationBridge:
    def __init__(self, case, guard):
        editorial._enabled()
        self.case, self.guard = case, guard
        self.policy = getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None)
        if not isinstance(self.policy, PublicationAuthority):
            raise cases.CaseConflict("operational_publication_authority_required")
        self.epoch = self.policy_epoch()
        self.configuration, self.rights = source_configuration(), rights_state(case)
        self.source_authority = getattr(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", None)
        self.checks, self.authors, self.sources, self.deadlines = [], {}, {}, []
        guard.adapters.append(self)

    def policy_epoch(self):
        try:
            result = self.policy.projection_epoch()
        except Exception as exc:
            raise cases.CaseConflict("operational_publication_epoch_required") from exc
        if type(result) is not str or not 1 <= len(result) <= 131072:
            raise cases.CaseConflict("operational_publication_epoch_required")
        return result

    def call(self, values):
        try:
            return self.policy.permits(**values) is True
        except Exception as exc:
            raise cases.CaseConflict("operational_publication_policy_unavailable") from exc

    def permit(self, edition, action, *, required=False):
        if action not in ACTION_MAP:
            raise cases.CaseConflict("operational_publication_action_unavailable")
        if not self.guard.permit_resource(
            self.case, ACTION_MAP[action], resource(self.case, edition), required=required
        ):
            return False
        values = dict(
            provider_id=self.guard.provider_id,
            subject_id=self.guard.actor.subject_id,
            auth_epoch=self.guard.actor.auth_epoch,
            case_ref=self.case.public_ref,
            action=action,
        )
        allowed = self.call(values)
        self.checks.append((values, allowed))
        if required and not allowed:
            raise cases.CaseConflict("operational_publication_action_denied")
        return allowed

    def canonical_author(self, row):
        if row.provider_id != self.guard.provider_id:
            raise cases.CaseConflict("operational_publication_canonical_author_changed")
        actor = cases._identity(self.guard.directory, row.subject_id, self.case)
        if actor.auth_epoch != row.auth_epoch:
            raise cases.CaseConflict("operational_publication_canonical_author_changed")
        self.authors[row.subject_id] = identity.pin(actor)
        self.deadlines.append(actor.valid_until)

    def source(self, edition):
        answer, decision = editorial._approved(self.case, edition)
        self.canonical_author(answer)
        self.canonical_author(decision)
        citations = editorial._citation_snapshot(answer)
        if edition.citations != citations:
            raise cases.CaseConflict("publication_citation_source_changed")
        until = editorial._require_publication_sources(self.case, edition.citations)
        if until is not None:
            self.deadlines.append(until)
        self.sources[str(edition.pk)] = (edition, answer, citations)

    def callbacks(self):
        for values, expected in self.checks:
            if self.call(values) != expected:
                raise cases.CaseConflict("operational_publication_grant_changed")
        for subject, expected in self.authors.items():
            current = cases._identity(self.guard.directory, subject, self.case)
            if identity.pin(current) != expected:
                raise cases.CaseConflict("operational_publication_canonical_author_changed")
            self.deadlines.append(current.valid_until)
        # Precise/timed annotation checks are retained in answer_sources. Repeat
        # ordinary citation rights here without opening new annotation contexts.
        for edition, answer, expected in self.sources.values():
            if editorial._citation_snapshot(answer) != expected:
                raise cases.CaseConflict("publication_citation_source_changed")
            until = editorial._require_publication_citations(self.case, edition.citations)
            if until is not None:
                self.deadlines.append(until)

    def final_pins(self):
        editorial._enabled()
        if (
            getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None) is not self.policy
            or self.policy_epoch() != self.epoch
            or source_configuration() != self.configuration
            or getattr(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", None) is not self.source_authority
            or rights_state(self.case) != self.rights
            or any(timezone.now() >= value for value in self.deadlines)
        ):
            raise cases.CaseConflict("operational_publication_source_changed")
        if apps.is_installed("apps.case_citations"):
            from apps.case_citations.services import _citation_snapshots_for_locked_answer

            for _edition, answer, expected in self.sources.values():
                pure = [
                    {"source": row["source"], "source_sha256": row["source_sha256"]}
                    for row in _citation_snapshots_for_locked_answer(answer)
                ]
                if pure != expected:
                    raise cases.CaseConflict("publication_citation_source_changed")


def available(case, guard):
    return guard.publication_feature and guard.permit(
        case, "READ_PUBLICATION_MANAGER", "publication_manager"
    )


def _case(case_ref, guard):
    if type(case_ref) is not str or not 1 <= len(case_ref) <= 128 or not guard.publication_feature:
        raise cases.CaseConflict("operational_publication_unavailable")
    case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
    if case is None:
        raise cases.CaseConflict("operational_publication_unavailable")
    guard.permit(case, "READ_CASE", "case", required=True)
    guard.permit(case, "READ_PUBLICATION_MANAGER", "publication_manager", required=True)
    cases._verify(case)
    return case


def _projection(case, guard, bridge, *, saved=False):
    editions = list(
        PublicationEdition.objects.filter(case=case)
        .select_related("answer", "decision")
        .order_by("number")[:65]
    )
    if len(editions) > 64:
        raise cases.CaseConflict("operational_publication_history_bound")
    rows = []
    latest = editions[-1].pk if editions else None
    for edition in editions:
        if not bridge.permit(edition, "READ"):
            continue
        editorial._verify(edition)
        events = list(edition.actions.order_by("pk"))
        actions = {row.action for row in events}
        current = False
        try:
            bridge.source(edition)
            current = True
        except cases.CaseConflict:
            pass
        options = []
        actor = guard.provider_id, guard.actor.subject_id
        creator = edition.provider_id, edition.subject_id
        if current and edition.pk == latest and not actions and actor != creator:
            options.append("REVIEW")
        review = next((row for row in events if row.action == "REVIEW"), None)
        if (
            current
            and edition.pk == latest
            and actions == {"REVIEW"}
            and actor
            not in {
                creator,
                (edition.decision.provider_id, edition.decision.subject_id),
                (review.provider_id, review.subject_id),
            }
        ):
            options.append("APPROVE")
        if "WITHDRAW" not in actions:
            options.append("WITHDRAW")
        options = [action for action in options if bridge.permit(edition, action)]
        dto = editorial._projection(edition, editorial=True)
        dto.update(
            current=current,
            subject_id=edition.subject_id,
            action_count=len(events),
            history=[
                {"action": row.action, "subject_id": row.subject_id, "created_at": row.created_at}
                for row in events
            ],
            options=options,
        )
        rows.append(dto)
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "subject": guard.actor.subject_id,
        "role": guard.actor.role,
        "editions": rows,
        "saved": saved,
    }


@contextmanager
def projection(*, case_ref, **common):
    with scope(**common) as guard, answer_sources.retain(guard):
        case = _case(case_ref, guard)
        yield _projection(case, guard, PublicationBridge(case, guard))


@contextmanager
def decide(
    *,
    case_ref,
    edition_id,
    content_sha256,
    action,
    confirmed,
    expected_actions,
    expected_revision,
    expected_evidence_version,
    **common,
):
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if (
        action not in {"REVIEW", "APPROVE", "WITHDRAW"}
        or confirmed is not True
        or type(expected_actions) is not int
        or not 0 <= expected_actions <= 2
    ):
        raise cases.CaseConflict("operational_publication_confirmation_required")
    with scope(**common) as guard, answer_sources.retain(guard):
        case = _case(case_ref, guard)
        cases._versions(case, expected_revision, expected_evidence_version)
        edition = (
            PublicationEdition.objects.select_related("answer", "decision")
            .filter(pk=cases._uuid(edition_id), case=case)
            .first()
        )
        if edition is None or edition.content_sha256 != content_sha256:
            raise cases.CaseConflict("operational_publication_edition_changed")
        bridge = PublicationBridge(case, guard)
        bridge.permit(edition, "READ", required=True)
        bridge.permit(edition, action, required=True)
        if action != "WITHDRAW":
            bridge.source(edition)
        if edition.actions.count() != expected_actions:
            raise cases.CaseConflict("operational_publication_action_changed")
        if action == "REVIEW" and (edition.provider_id, edition.subject_id) == (
            guard.provider_id,
            guard.actor.subject_id,
        ):
            raise cases.CaseConflict("operational_publication_independent_review_required")
        event = editorial._append_action_locked(
            case=case,
            edition=edition,
            actor=guard.actor,
            provider=guard.provider,
            action=action,
            reviewed=confirmed,
            before_append=guard.finish,
        )
        guard.account_for_append(event)
        yield _projection(case, guard, bridge, saved=True)
