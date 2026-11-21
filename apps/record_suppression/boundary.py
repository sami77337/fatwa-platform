"""Actual administrative identities and explicit finite mandates through final render."""

from contextlib import contextmanager

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.casework import services as cases
from apps.data_privacy import services as principals
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.operational_workspace import identity
from apps.platform_recovery.integration import mutation_context

from . import catalog, store
from .authority import Grant, SuppressionAuthority
from .catalog import SuppressionDenied


def policy():
    if store.configured() is None:
        raise SuppressionDenied("suppression_explicit_configuration_required")
    authority = getattr(settings, "FATWA_RECORD_SUPPRESSION_AUTHORITY", None)
    if not isinstance(authority, SuppressionAuthority):
        raise SuppressionDenied("suppression_management_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise SuppressionDenied("suppression_policy_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise SuppressionDenied("suppression_policy_snapshot_required")
    return authority, epoch


class Guard:
    def __init__(self, provider, subject_id, session_deadline, *, allow_pending):
        self.selected = policy()
        self.provider = provider
        actor = identity.validate(provider.resolve(subject_id), subject_id=subject_id)
        if actor.role not in catalog.ROLES:
            raise SuppressionDenied("suppression_administrative_role_required")
        self.principal = principals.staff_principal(provider, actor)
        self.actor, self.provider_id = actor, self.principal.provider_id
        self.deadline = self.principal.valid_until
        if session_deadline is not None:
            if not identity.valid_deadline(session_deadline):
                raise SuppressionDenied("suppression_session_expired")
            self.deadline = min(self.deadline, session_deadline)
        self.saved = store.snapshot(allow_pending=allow_pending)
        self.calls, self.sources = [], {}
        self.allow_pending = allow_pending
        self.choices = None

    def _call(self, values):
        try:
            import json

            result = self.selected[0].authorize(**json.loads(catalog.canonical(values)))
        except Exception as exc:
            raise SuppressionDenied("suppression_management_denied") from exc
        if type(result) is not Grant or not identity.valid_deadline(result.valid_until):
            raise SuppressionDenied("suppression_management_denied")
        self.deadline = min(self.deadline, result.valid_until)

    def require(self, action, resource=None):
        values = dict(
            provider_id=self.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            role=self.actor.role,
            action=action,
            resource=resource,
        )
        self._call(values)
        self.calls.append(values)

    def resources(self):
        if self.choices is None:
            try:
                choices = self.selected[0].resources(
                    provider_id=self.provider_id,
                    subject_id=self.actor.subject_id,
                    auth_epoch=self.actor.auth_epoch,
                    role=self.actor.role,
                )
            except Exception as exc:
                raise SuppressionDenied("suppression_resources_unavailable") from exc
            if type(choices) is not tuple or len(choices) > 512:
                raise SuppressionDenied("suppression_resources_invalid")
            self.choices = set()
            for choice in choices:
                if (
                    type(choice) is not tuple
                    or len(choice) != 2
                    or choice[0] not in catalog.TARGETS
                ):
                    raise SuppressionDenied("suppression_resources_invalid")
                key = (choice[0], catalog.uuid_text(choice[1]))
                if key in self.choices:
                    raise SuppressionDenied("suppression_resources_invalid")
                self.choices.add(key)
        return self.choices

    def target(self, kind, identifier):
        if (kind, identifier) not in self.resources():
            raise SuppressionDenied("suppression_target_outside_mandate")
        target = catalog.target(kind, identifier)
        if target.case_ref and target.case_ref not in self.actor.case_keys:
            raise SuppressionDenied("suppression_case_scope_denied")
        self.sources[(kind, identifier)] = target
        return target

    def resource(self, target):
        head = self.saved.heads.get((target.kind, target.identifier))
        return {
            "kind": target.kind,
            "id": target.identifier,
            "source_digest": target.source_digest,
            "case_id": target.case_id,
            "case_ref": target.case_ref,
            "state": head["state"] if head else "ACTIVE",
            "version": head["version"] if head else 0,
            "head": catalog.digest(head) if head else catalog.ZERO,
        }

    def callbacks(self):
        for values in self.calls:
            self._call(values)
        self.deadline = min(self.deadline, principals._identity_callbacks(self.principal))

    def final_pins(self):
        selected = policy()
        if selected[0] is not self.selected[0] or selected[1] != self.selected[1]:
            raise SuppressionDenied("suppression_management_changed")
        principals._identity_pins(self.principal)
        current = store.snapshot(allow_pending=self.allow_pending)
        if (
            current is None
            or current.config != self.saved.config
            or current.events != self.saved.events
            or [store.body(row) for row in current.saved]
            != [store.body(row) for row in self.saved.saved]
        ):
            raise SuppressionDenied("suppression_ledger_changed")
        for target in self.sources.values():
            if catalog.target(target.kind, target.identifier) != target:
                raise SuppressionDenied("suppression_source_changed")
        if self.deadline <= timezone.now():
            raise SuppressionDenied("suppression_management_expired")

    def finish(self):
        self.callbacks()
        self.final_pins()

    def append(self, value, row):
        # Account for exactly our admitted append, never adopt a callback's work.
        self.saved.events = [*self.saved.events, value]
        self.saved.saved = [*self.saved.saved, row]


@mutation_context
@contextmanager
def scope(
    *,
    provider,
    subject_id,
    synthetic_fixtures_only=False,
    session_deadline=None,
    allow_pending=False,
):
    cases._guard(synthetic_fixtures_only)
    policy()
    with synthetic_queue_atomic(), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        store.lock()
        guard = Guard(provider, subject_id, session_deadline, allow_pending=allow_pending)
        guard.require("ENTER")
        guard.final_pins()
        from apps.staff_sessions.integration import retain_final_guard

        retain_final_guard(
            guard.final_pins, failure=cases.CaseConflict, code="suppression_response_unavailable"
        )
        yield guard
        guard.finish()
