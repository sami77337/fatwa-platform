"""Current scoped identity and every consumed source permission, through rendering."""

import os
from contextlib import ExitStack, contextmanager

from django.conf import settings
from django.utils import timezone

from apps.case_citations.services import _projection_expiry_guard
from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.knowledge_links.authority import KnowledgeAuthority
from apps.mufti_review.identity import resolve_identity
from apps.platform_recovery.integration import mutation_context
from apps.research_library.services import identity_snapshot
from apps.research_workspace.reference_batch import _epoch as research_epoch
from apps.research_workspace.rights import ResearchRights
from apps.source_rights.models import (
    RightsAction,
    RightsRevision,
    SourceRegistration,
    SourceVersion,
)
from apps.transcript_case_links.models import TranscriptLink

from . import governance_pins, sources
from .authority import SearchAuthority
from .recordings import RecordingSources

MAX_CASES = 32


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_CANONICAL_SEARCH_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("canonical_search_disabled")


def _epoch(value):
    try:
        result = value.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("search_policy_snapshot_required") from exc
    if type(result) is not str or not 1 <= len(result) <= 4000:
        raise cases.CaseConflict("search_policy_snapshot_required")
    return result


def snapshot():
    enabled()
    value = getattr(settings, "FATWA_CANONICAL_SEARCH_AUTHORITY", None)
    if not isinstance(value, SearchAuthority):
        raise cases.CaseConflict("search_authority_required")
    return (
        value,
        _epoch(value),
        id(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
    )


def assert_snapshot(initial):
    current = snapshot()
    if current[0] is not initial[0] or current[1:] != initial[1:]:
        raise cases.CaseConflict("search_authority_changed")


def transcript_snapshot(case_ids):
    """Unusable optional policies exclude transcripts, never expose their copies."""
    present = TranscriptLink.objects.filter(case_id__in=case_ids).exists()
    if not present:
        return False, ()
    research = getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None)
    knowledge = getattr(settings, "FATWA_KNOWLEDGE_LINKS_AUTHORITY", None)
    values = tuple(
        getattr(settings, name, None)
        for name in (
            "FATWA_RESEARCH_WORKSPACE_ENABLED",
            "FATWA_KNOWLEDGE_LINKS_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENFORCED",
            "FATWA_SOURCE_RIGHTS_ENABLED",
        )
    )
    available = (
        isinstance(research, ResearchRights)
        and isinstance(knowledge, KnowledgeAuthority)
        and values[0] is True
        and values[1] is True
    )
    try:
        epochs = (research_epoch(research), _epoch(knowledge)) if available else ()
    except cases.CaseConflict:
        available, epochs = False, ()
    registrations = SourceRegistration.objects.filter(case_id__in=case_ids)
    revisions = RightsRevision.objects.filter(case_id__in=case_ids)
    now = timezone.now()
    ledger = (
        sources.frozen_rows(registrations.order_by("pk").values_list("pk", "case_id", "source_id")),
        sources.frozen_rows(
            revisions.order_by("pk").values_list("pk", "source_id", "number", "valid_until")
        ),
        tuple(str(row.pk) for row in revisions.filter(valid_until__lte=now).order_by("pk")),
        sources.frozen_rows(
            RightsAction.objects.filter(revision__case_id__in=case_ids)
            .order_by("pk")
            .values_list("pk", "revision_id", "action")
        ),
        sources.frozen_rows(
            SourceVersion.objects.filter(sourceregistration__case_id__in=case_ids)
            .distinct()
            .order_by("pk")
            .values_list("pk", "sha256")
        ),
    )
    configuration = tuple((type(value), value) for value in values)
    source_authority = getattr(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", None)
    return available, (
        id(research),
        research,
        id(knowledge),
        knowledge,
        epochs,
        configuration,
        ledger,
        id(source_authority),
        source_authority,
    )


def history(case_ids):
    from .models import SearchDocument, SearchGeneration

    return (
        sources.frozen_rows(
            SearchGeneration.objects.filter(case_id__in=case_ids)
            .order_by("pk")
            .values_list("pk", "digest")
        ),
        sources.frozen_rows(
            SearchDocument.objects.filter(generation__case_id__in=case_ids)
            .order_by("pk")
            .values_list("pk", "digest")
        ),
    )


def _actor(value):
    return value.subject_id, value.role, value.active, value.auth_epoch, value.case_keys


class Scope:
    def __init__(self, *, provider, actor, initial, identity, case_ids, action):
        self.provider, self.actor, self.initial, self.identity = provider, actor, initial, identity
        self.case_ids, self.action = tuple(case_ids), action
        self.cases = {}
        self.source_state = sources.fingerprint(self.case_ids)
        self.source_policy = transcript_snapshot(self.case_ids)
        self.recordings = RecordingSources(self.case_ids, provider, actor)
        self.index_state = history(self.case_ids)
        self.governance = governance_pins.Pins(self.case_ids)
        self.expected_generations, self.expected_documents = set(), set()
        self.documents = {}
        self.extra_permissions = set()

    def permit(self, case):
        self._permit(case, self.action)

    def require(self, case, action):
        if action not in {"VIEW", "REBUILD", "SEARCH", "OPEN"} | governance_pins.ACTIONS:
            raise cases.CaseConflict("search_scope_invalid")
        if action in governance_pins.ACTIONS:
            governance_pins.enabled()
            governance_pins.require_configured_identity(self.provider)
        self._permit(case, action)
        self.extra_permissions.add((str(case.pk), action))

    def _permit(self, case, action):
        try:
            result = self.initial[0].permits(
                provider_id=self.provider.provider_id,
                subject_id=self.actor.subject_id,
                auth_epoch=self.actor.auth_epoch,
                case_ref=case.public_ref,
                action=action,
            )
        except Exception as exc:
            raise cases.CaseConflict("search_authority_unavailable") from exc
        if result is not True:
            raise cases.CaseConflict("search_action_denied")
        from apps.data_privacy.integration import staff as privacy

        privacy(
            "CASE",
            case.pk,
            provider=self.provider,
            actor=self.actor,
            action="SEARCH" if action in {"SEARCH", "REBUILD"} else "READ",
        )

    def read(self, case):
        result = self._read(case)
        self.documents[str(case.pk)] = {row.key: row for row in result}
        return result

    def _read(self, case):
        result = sources.read(
            case,
            self.actor,
            self.provider,
            transcripts_available=self.source_policy[0],
            privacy_action="SEARCH" if self.action in {"SEARCH", "REBUILD"} else "READ",
        ) + self.recordings.read(case)
        if len(result) > sources.MAX_DOCUMENTS:
            raise cases.CaseConflict("search_document_capacity")
        return result

    def wrote(self, generation, documents):
        self.expected_generations.add((str(generation.pk), generation.digest))
        self.expected_documents.update((str(row.pk), row.digest) for row in documents)

    def callbacks(self):
        # All callbacks finish before any final pure comparison. Rechecking the
        # first result after the last one alone is insufficient for mixed grants.
        for case in self.cases.values():
            self.permit(case)
            if str(case.pk) in self.documents:
                current = {row.key: row for row in self._read(case)}
                if current != self.documents[str(case.pk)]:
                    raise cases.CaseConflict("search_current_sources_changed")
        for case_id, action in sorted(self.extra_permissions):
            self._permit(self.cases[case_id], action)
        fresh = resolve_identity(self.provider, self.actor.subject_id)
        if _actor(fresh) != _actor(self.actor) or timezone.now() >= self.actor.valid_until:
            raise cases.CaseConflict("search_identity_changed")

    def verify_bytes(self):
        self.recordings.verify_bytes()

    def final_pins(self):
        self.recordings.final_pins()
        if timezone.now() >= self.actor.valid_until:
            raise cases.CaseConflict("search_identity_changed")
        assert_snapshot(self.initial)
        if identity_snapshot(self.provider) != self.identity:
            raise cases.CaseConflict("search_identity_changed")
        if transcript_snapshot(self.case_ids) != self.source_policy:
            raise cases.CaseConflict("search_source_policy_changed")
        if sources.fingerprint(self.case_ids) != self.source_state:
            raise cases.CaseConflict("search_source_changed")
        expected = (
            tuple(sorted(set(self.index_state[0]) | self.expected_generations)),
            tuple(sorted(set(self.index_state[1]) | self.expected_documents)),
        )
        actual = history(self.case_ids)
        if (tuple(sorted(actual[0])), tuple(sorted(actual[1]))) != expected:
            raise cases.CaseConflict("search_index_changed")
        self.governance.finish()

    def finish(self):
        self.callbacks()
        self.verify_bytes()
        self.final_pins()


@mutation_context
@contextmanager
def boundary(
    *, case_id, subject_id, provider, action="VIEW", scope="CASE", synthetic_fixtures_only=False
):
    if action not in {
        "VIEW",
        "REBUILD",
        "SEARCH",
        "OPEN",
    } | governance_pins.ACTIONS or scope not in {"CASE", "SCOPED"}:
        raise cases.CaseConflict("search_scope_invalid")
    if action in governance_pins.ACTIONS:
        governance_pins.enabled()
        governance_pins.require_configured_identity(provider)
        if scope != "CASE":
            raise cases.CaseConflict("search_dictionary_case_scope_required")
    enabled()
    cases._guard(synthetic_fixtures_only)
    from apps.data_privacy.integration import projection
    from apps.data_privacy.integration import staff as privacy
    from apps.data_privacy.services import PrivacyDenied

    with projection() as privacy_projection, synthetic_queue_atomic(), ExitStack() as stack:
        identity = identity_snapshot(provider)
        initial = snapshot()
        actor = resolve_identity(provider, subject_id)
        selected = Case.objects.filter(public_ref__in=actor.case_keys)
        if scope == "CASE":
            selected = selected.filter(pk=cases._uuid(case_id))
        ids = list(selected.order_by("pk").values_list("pk", flat=True)[: MAX_CASES + 1])
        if not ids or cases._uuid(case_id) not in ids or len(ids) > MAX_CASES:
            raise cases.CaseConflict("search_case_scope_unavailable")
        stack.enter_context(_projection_expiry_guard())
        locked = {}
        for pk in ids:
            try:
                privacy(
                    "CASE",
                    pk,
                    provider=provider,
                    actor=actor,
                    action="SEARCH" if action in {"SEARCH", "REBUILD"} else "READ",
                )
                case, current = stack.enter_context(
                    cases._staff_case(pk, subject_id, provider, True)
                )
            except PrivacyDenied:
                continue
            if _actor(current) != _actor(actor):
                raise cases.CaseConflict("search_identity_changed")
            locked[str(pk)] = case
        if str(cases._uuid(case_id)) not in locked:
            raise cases.CaseConflict("search_case_scope_unavailable")
        ids = [case.pk for case in locked.values()]
        # Take the source/index snapshot only after all canonical locks are held.
        # This admits an exact idempotent replay after a concurrent rebuild.
        # Earlier identity callbacks cannot leave stale in-memory case pointers.
        for case in locked.values():
            case.refresh_from_db()
            cases._verify(case)
        context = Scope(
            provider=provider,
            actor=actor,
            initial=initial,
            identity=identity,
            case_ids=ids,
            action=action,
        )
        context.cases = locked
        for case in locked.values():
            context.permit(case)
        from apps.derived_maintenance.rebuild import retain_owner

        retain_owner(verify_bytes=context.verify_bytes, final_pins=context.final_pins)
        retain_owner(final_pins=privacy_projection.final_pins)
        yield context
        context.finish()
