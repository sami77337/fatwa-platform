"""Explicit classification management; no permission to read target contents."""

from contextlib import contextmanager
from dataclasses import dataclass, replace

from django.apps import apps
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.casework import services as cases
from apps.operational_workspace import identity
from apps.platform_recovery.integration import mutation_context, mutation_service

from . import integration, services
from .catalog import TARGETS, locate

MAX_TARGETS = 2048


def principal(provider, subject_id, session_deadline=None):
    actor = identity.validate(provider.resolve(subject_id), subject_id=subject_id)
    if session_deadline is not None:
        if not identity.valid_deadline(session_deadline):
            raise services.PrivacyDenied("privacy_session_expired")
        actor = replace(actor, valid_until=min(actor.valid_until, session_deadline))
    return services.staff_principal(provider, actor)


@dataclass(slots=True)
class ManagementUse:
    target: object
    principal: object
    selected: tuple
    before: str
    deadline: object

    def callbacks(self):
        rows = services.history(self.target)
        deadline = services._permission(
            self.selected,
            self.principal,
            self.target,
            rows[-1].level if rows else "",
            "VIEW_CLASSIFICATION",
        )
        self.deadline = min(self.deadline, deadline, services._identity_callbacks(self.principal))

    def final_pins(self):
        services.assert_policy(self.selected)
        services._identity_pins(self.principal)
        rows = services.history(self.target)
        if (
            locate(self.target.kind, self.target.identifier) != self.target
            or (rows[-1].digest if rows else services.ZERO) != self.before
            or self.deadline <= timezone.now()
        ):
            raise services.PrivacyDenied("privacy_management_source_changed")


def _locked(target, actor):
    if target.case_ref and target.case_ref not in actor.case_keys:
        raise services.PrivacyDenied("privacy_classification_scope_denied")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
    if target.case_id:
        cases.Case.objects.select_for_update().get(pk=target.case_id)
    services._lock(target)
    if locate(target.kind, target.identifier) != target:
        raise services.PrivacyDenied("privacy_source_changed")


def _inspect(kind, identifier, reader):
    selected = services.policy()
    target = locate(kind, identifier)
    _locked(target, reader.actor)
    history = services.history(target)
    latest = history[-1] if history else None
    deadline = services._permission(
        selected, reader, target, latest.level if latest else "", "VIEW_CLASSIFICATION"
    )
    identity_deadline = services._identity_callbacks(reader)
    use = ManagementUse(
        target,
        reader,
        selected,
        latest.digest if latest else services.ZERO,
        min(deadline, identity_deadline),
    )
    use.final_pins()
    for scope in services.SCOPES.get():
        scope.uses.append(use)
    return {
        "kind": kind,
        "id": target.identifier,
        "case_ref": target.case_ref,
        "source_digest": target.source_digest,
        "digest": use.before,
        "level": latest.level if latest else "",
        "source_changed": bool(latest and latest.source_digest != target.source_digest),
        "history": [
            {
                "revision": row.number,
                "level": row.level,
                "note": row.note,
                "subject_id": row.subject_id,
                "created_at": row.created_at,
                "digest": row.digest,
                "source_digest": row.source_digest,
            }
            for row in reversed(history)
        ],
    }


@mutation_context
@integration.contextual
@contextmanager
def inspect(
    *, kind, identifier, provider, subject_id, synthetic_fixtures_only=False, session_deadline=None
):
    cases._guard(synthetic_fixtures_only)
    reader = principal(provider, subject_id, session_deadline)
    yield _inspect(kind, identifier, reader)


def _candidates(actor):
    case_ids = list(
        cases.Case.objects.filter(public_ref__in=actor.case_keys).values_list("pk", flat=True)
    )
    for kind, (label, _hash, case_field) in TARGETS.items():
        if not apps.is_installed("apps." + label.split(".")[0]):
            continue
        model = apps.get_model(label)
        condition = Q(**{case_field + "__in": case_ids})
        if kind == "SOURCE_VERSION":
            condition |= Q(sourceregistration__case_id__in=case_ids)
        if kind == "SOURCE_RECEIPT":
            from apps.source_case_intake.services import REVIEW_SCOPE

            if REVIEW_SCOPE in actor.case_keys:
                condition |= Q(evidencebinding__isnull=True)
        for identifier in (
            model.objects.filter(condition)
            .distinct()
            .order_by("pk")
            .values_list("pk", flat=True)[: MAX_TARGETS + 1]
        ):
            yield kind, identifier


@mutation_service
@integration.projected
def catalog(*, provider, subject_id, synthetic_fixtures_only=False, session_deadline=None):
    cases._guard(synthetic_fixtures_only)
    services.policy()
    reader = principal(provider, subject_id, session_deadline)
    result = []
    for index, (kind, identifier) in enumerate(_candidates(reader.actor), 1):
        if index > MAX_TARGETS:
            raise services.PrivacyDenied("privacy_management_capacity")
        try:
            value = _inspect(kind, identifier, reader)
        except services.PrivacyDenied:
            continue
        result.append(
            {key: value[key] for key in ("kind", "id", "case_ref", "level", "source_changed")}
        )
    return {"rows": result, "total": len(result), "role": reader.role}
