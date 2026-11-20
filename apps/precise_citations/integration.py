"""Canonical veto hooks. A citation never releases either answer or source bytes."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.apps import apps
from django.conf import settings
from django.db import connection

from apps.casework import services as cases

_USES = ContextVar("precise_citation_use_boundaries", default=())


@contextmanager
def answer_use_boundary():
    """Coordinator wraps the COMPLETE approval/delivery/public projection in this."""
    guards = []
    token = _USES.set((*_USES.get(), guards))
    try:
        yield
        # Closed child contexts leave no out-of-order transaction or ContextVar
        # on the stack. Repeat every callback first, then every pure pin last.
        for guard in guards:
            for source in guard.libraries.values():
                source.check_permissions()
            guard.callbacks()
        for guard in guards:
            guard.verify_bytes()
        for guard in guards:
            guard.final_pins(verify_files=False)
    finally:
        _USES.reset(token)


def _present(answer):
    if answer is None:
        return False
    if not apps.is_installed("apps.precise_citations"):
        table = "precise_citations_citationset"
        if table in connection.introspection.table_names():
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT 1 FROM "{table}" WHERE answer_id=%s LIMIT 1', [answer.pk])
                if cursor.fetchone():
                    raise cases.CaseConflict("precise_citation_schema_unavailable")
        return False
    from .models import CitationSet

    return CitationSet.objects.filter(answer=answer).exists()


def dependency_case_ids(case_ids):
    if not apps.is_installed("apps.precise_citations"):
        return set(case_ids)
    from .boundary import dependency_case_ids as implementation

    return implementation(case_ids)


def lock_dependencies(case_id):
    if not apps.is_installed("apps.precise_citations"):
        return None
    from .boundary import lock_dependencies as implementation

    return implementation(case_id)


def prelock_cases(case_ids):
    """Compose a whole candidate set before a reader takes its first case lock."""
    if not apps.is_installed("apps.precise_citations"):
        return set(case_ids)
    if not connection.in_atomic_block:
        raise cases.CaseConflict("precise_citation_transaction_required")
    from apps.casework.models import Case

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
    identifiers = dependency_case_ids(case_ids)
    list(Case.objects.filter(pk__in=identifiers).order_by("pk").select_for_update())
    return identifiers


def require_for_answer(answer, *, actor=None, provider=None):
    if not _present(answer):
        return None
    if not connection.in_atomic_block or not _USES.get():
        raise cases.CaseConflict("precise_citation_outer_use_boundary_required")
    before_approval = actor is not None and getattr(answer, "decision", None) is None
    if actor is None:
        decision = getattr(answer, "decision", None)
        provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if (
            decision is None
            or decision.action != "APPROVE"
            or getattr(provider, "provider_id", None) != decision.provider_id
        ):
            raise cases.CaseConflict("precise_citation_approver_unavailable")
        actor = cases._identity(provider, decision.subject_id, answer.case)
        if actor.auth_epoch != decision.auth_epoch:
            raise cases.CaseConflict("precise_citation_approver_changed")
    if provider is None:
        raise cases.CaseConflict("precise_citation_approver_unavailable")
    from .boundary import scope
    from .models import CitationSet
    from .services import read_locked

    record = CitationSet.objects.get(answer=answer)
    with scope(
        case_id=answer.case_id,
        subject_id=actor.subject_id,
        provider=provider,
        synthetic_fixtures_only=True,
        restricted_case_ids=dependency_case_ids([answer.case_id]),
    ) as guard:
        read_locked(guard, case_id=answer.case_id, set_id=record.pk, require_review=True)
    guard.pending_approval = (
        (str(answer.pk), provider.provider_id, actor.subject_id, actor.auth_epoch)
        if before_approval
        else None
    )
    for outer in _USES.get():
        outer.append(guard)
    deadlines = [*guard.deadlines]
    for source in guard.libraries.values():
        deadlines.extend(source.deadlines)
    return min(deadlines, default=None)


def validate_for_approval(answer, *, actor, provider):
    return require_for_answer(answer, actor=actor, provider=provider)


def canonical_written(case_id):
    """Only canonical writer calls this immediately after its intended _event.

    Other cases, citation/source histories, policy/identity generations and bytes
    retain their original pins. Never call this from a reader or after rendering.
    """
    seen = set()
    for guards in _USES.get():
        for guard in guards:
            if (
                id(guard) not in seen
                and guard.owner_case_id == cases._uuid(case_id)
                and getattr(guard, "pending_approval", None) is not None
            ):
                from apps.casework.models import Case

                case = Case.objects.select_related("approved_answer__decision").get(pk=case_id)
                baseline = guard.canonical[guard.owner_case_id][0][0]
                decision = getattr(case.approved_answer, "decision", None)
                if (
                    decision is None
                    or decision.action != "APPROVE"
                    or case.stage != "ANSWERED"
                    or case.revision != baseline["revision"] + 1
                    or case.evidence_version != baseline["evidence_version"]
                    or (
                        str(decision.answer_id),
                        decision.provider_id,
                        decision.subject_id,
                        decision.auth_epoch,
                    )
                    != guard.pending_approval
                ):
                    raise cases.CaseConflict("precise_citation_unexpected_canonical_write")
                guard.written(case_id)
                guard.pending_approval = None
                seen.add(id(guard))
