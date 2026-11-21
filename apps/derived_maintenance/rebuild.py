"""A fresh bounded AI request; all model execution remains in the central gateway."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from . import boundary, services
from .catalog import DerivedDenied

_RETAINERS = ContextVar("derived_current_rebuild_owners", default=())


@contextmanager
def retaining(guard):
    if type(guard) is not boundary.Guard:
        raise DerivedDenied("derived_owner_guard_required")
    token = _RETAINERS.set((*_RETAINERS.get(), guard))
    try:
        yield
    finally:
        _RETAINERS.reset(token)


def retain_owner(*, final_pins, verify_bytes=None):
    """A local rebuild scope only; no permissions or principal are substituted."""
    for guard in _RETAINERS.get():
        guard.retain_owner(final_pins=final_pins, verify_bytes=verify_bytes)


@dataclass
class RebuildIntent:
    plan: dict
    base: dict
    guards: list = field(default_factory=list)

    def binding(self):
        proposal = self.plan["proposal"]
        return [
            proposal["kind"],
            proposal["identifier"],
            proposal["clearance"],
            proposal["request_key"],
        ]

    @contextmanager
    def stage(self):
        with boundary.scope(**self.base) as guard:
            if self.guards:
                previous = self.guards[-1]
                guard.retain_owner(
                    verify_bytes=previous.verify_owners, final_pins=previous.final_pins
                )
            services._check_plan(guard, self.plan)
            self.guards.append(guard)
            with retaining(guard):
                yield guard
            # The boundary now repeats previous and current owner pure checks
            # AFTER its own final callbacks, inside the still-open transaction.

    def record(self, guard, run, status):
        proposal = self.plan["proposal"]
        target = guard.targets[proposal["kind"], proposal["identifier"]]
        row = services._rebuild_record(
            guard,
            parent=target,
            child_id=run.pk,
            child_digest=run.digest,
            status=status,
            request_key=proposal["request_key"],
            reason=proposal["reason"],
        )
        for prior in self.guards:
            prior.rebuilt(row)

    def replay(self, run):
        from .models import DerivativeRebuild

        row = DerivativeRebuild.objects.filter(pk=self.plan["proposal"]["request_key"]).first()
        if row is None or row.child_id != run.pk or row.child_digest != run.digest:
            raise DerivedDenied("derived_rebuild_attempt_incomplete")


@contextmanager
def gateway_stage(intent):
    if intent is None:
        yield None
    elif type(intent) is not RebuildIntent:
        raise DerivedDenied("derived_rebuild_intent_invalid")
    else:
        with intent.stage() as guard:
            yield guard


def regenerate(*, plan, base):
    from apps.ai_gateway import services as gateway

    intent = RebuildIntent(plan, base)
    with intent.stage():
        pass
    inputs, proposal = plan["inputs"], plan["proposal"]
    result = gateway.request_candidates(
        case_id=plan["resources"][0]["case_id"],
        subject_id=base["subject_id"],
        provider=base["provider"],
        synthetic_fixtures_only=True,
        query=proposal["parameters"]["query"],
        selection=inputs["selection"],
        start=inputs["start"],
        end=inputs["end"],
        expected_revision=inputs["case_revision"],
        expected_evidence_version=inputs["evidence_version"],
        request_key=proposal["request_key"],
        rebuild_intent=intent,
    )
    return dict(action="REBUILD", child_id=result["id"], status=result["status"]), intent
