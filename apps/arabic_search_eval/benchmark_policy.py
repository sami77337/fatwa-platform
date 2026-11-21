"""Current, explicit authorization for canonical benchmark development records."""

from abc import ABC, abstractmethod
from contextlib import contextmanager

from django.conf import settings

from apps.canonical_search import governance_pins, policy, services
from apps.canonical_search.text import digest
from apps.casework import services as cases
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context

from .models import (
    CanonicalBenchmarkDecision,
    CanonicalBenchmarkRun,
    EvaluationDecision,
    EvaluationRevision,
)

ACTIONS = frozenset({"READ", "PROPOSE", "JUDGE", "RUN", "REVIEW"})
MODELS = (EvaluationRevision, EvaluationDecision, CanonicalBenchmarkRun, CanonicalBenchmarkDecision)


class CanonicalBenchmarkAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Explicit case-scoped grant for one named action, never an implicit role."""
        raise NotImplementedError

    @abstractmethod
    def projection_epoch(self):
        """Changes whenever the authority's current grants change."""
        raise NotImplementedError


def flag():
    value = getattr(settings, "FATWA_CANONICAL_BENCHMARK_ENABLED", False)
    return type(value), value


def _configuration():
    if flag() != (bool, True):
        raise cases.CaseConflict("canonical_benchmark_disabled")
    authority = getattr(settings, "FATWA_CANONICAL_BENCHMARK_AUTHORITY", None)
    if not isinstance(authority, CanonicalBenchmarkAuthority):
        raise cases.CaseConflict("canonical_benchmark_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("canonical_benchmark_authority_unavailable") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 4000:
        raise cases.CaseConflict("canonical_benchmark_epoch_required")
    return authority, epoch


def _row_pin(row):
    return row._meta.model_name, str(row.pk), digest(services._body(row))


def history(case_id):
    rows = []
    for model in MODELS:
        if model is EvaluationDecision:
            selected = model.objects.filter(
                revision__case_id=case_id, revision__engine="CANONICAL_FTS"
            )
        else:
            selected = model.objects.filter(case_id=case_id)
            if model is EvaluationRevision:
                selected = selected.filter(engine="CANONICAL_FTS")
        rows.extend(_row_pin(row) for row in selected)
    return frozenset(rows)


class Scope:
    def __init__(self, search, case):
        from .benchmark import code_pin

        self.search, self.case = search, case
        self.authority, self.epoch = _configuration()
        self.initial = history(case.pk)
        self.code = code_pin()
        self.written, self.actions = set(), set()

    def permit(self, action):
        if action not in ACTIONS:
            raise cases.CaseConflict("canonical_benchmark_action_invalid")
        self._permit(action)
        self.actions.add(action)

    def _permit(self, action):
        try:
            allowed = self.authority.permits(
                provider_id=self.search.provider.provider_id,
                subject_id=self.search.actor.subject_id,
                auth_epoch=self.search.actor.auth_epoch,
                case_ref=self.case.public_ref,
                action=action,
            )
        except Exception as exc:
            raise cases.CaseConflict("canonical_benchmark_authority_unavailable") from exc
        if allowed is not True:
            raise cases.CaseConflict("canonical_benchmark_action_denied")

    def wrote(self, row):
        self.written.add(_row_pin(row))

    def callbacks(self):
        for action in sorted(self.actions):
            self._permit(action)

    def finish(self):
        from .benchmark import code_pin

        authority, epoch = _configuration()
        governance_pins.require_configured_identity(self.search.provider)
        if authority is not self.authority or epoch != self.epoch:
            raise cases.CaseConflict("canonical_benchmark_authority_changed")
        if history(self.case.pk) != self.initial | self.written:
            raise cases.CaseConflict("canonical_benchmark_history_changed")
        if code_pin() != self.code:
            raise cases.CaseConflict("canonical_benchmark_code_changed")


@mutation_context
@contextmanager
def boundary(*, action="READ", **base):
    _configuration()
    governance_pins.require_configured_identity(base["provider"])
    # The benchmark's final pure pins run after the canonical boundary's last
    # permission callback, but before the enclosing transaction can commit.
    with synthetic_queue_atomic():
        with policy.boundary(**base, action="SEARCH") as search:
            case = search.cases[str(cases._uuid(base["case_id"]))]
            context = Scope(search, case)
            context.permit(action)
            yield context
            context.callbacks()
        context.finish()
