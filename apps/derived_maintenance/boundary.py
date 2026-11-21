"""Metadata administration with real identities and pure checks after all callbacks."""

import json
from contextlib import contextmanager
from dataclasses import replace

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.casework import services as cases
from apps.data_privacy import services as principals
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.operational_workspace import identity
from apps.platform_recovery.integration import mutation_context

from . import catalog, store
from .authority import DerivedAuthority, Grant
from .catalog import DerivedDenied


def policy():
    if store.configured() is None:
        raise DerivedDenied("derived_explicit_configuration_required")
    authority = getattr(settings, "FATWA_DERIVED_MAINTENANCE_AUTHORITY", None)
    if not isinstance(authority, DerivedAuthority):
        raise DerivedDenied("derived_management_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise DerivedDenied("derived_policy_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise DerivedDenied("derived_policy_snapshot_required")
    return authority, epoch


def rebuild_history():
    from .models import DerivativeRebuild

    return tuple(
        (str(pk), digest)
        for pk, digest in DerivativeRebuild.objects.order_by("pk").values_list("pk", "digest")
    )


class Guard:
    def __init__(self, provider, subject_id, session_deadline, *, allow_pending):
        self.selected, self.provider = policy(), provider
        actor = identity.validate(provider.resolve(subject_id), subject_id=subject_id)
        if actor.role not in catalog.ROLES:
            raise DerivedDenied("derived_administrative_role_required")
        self.principal = principals.staff_principal(provider, actor)
        self.actor, self.provider_id = actor, self.principal.provider_id
        self.deadline = self.principal.valid_until
        if session_deadline is not None:
            if not identity.valid_deadline(session_deadline):
                raise DerivedDenied("derived_session_expired")
            self.deadline = min(self.deadline, session_deadline)
        self.saved = store.snapshot(allow_pending=allow_pending)
        self.allow_pending = allow_pending
        self.calls, self.targets, self.choices = [], {}, None
        self.rebuilds = set(rebuild_history())
        self.owner_checks = []

    def retain_owner(self, *, final_pins, verify_bytes=None):
        """Keep the exact consumed owner alive through our final callbacks."""
        self.owner_checks.append((verify_bytes, final_pins))

    def verify_owners(self):
        # Storage readers can execute code. Finish all such checks before any
        # final pure comparison, including owners retained by an earlier stage.
        for verify_bytes, _ in self.owner_checks:
            if verify_bytes is not None:
                verify_bytes()

    def _call(self, values):
        try:
            result = self.selected[0].authorize(**json.loads(catalog.canonical(values)))
        except Exception as exc:
            raise DerivedDenied("derived_management_denied") from exc
        if type(result) is not Grant or not identity.valid_deadline(result.valid_until):
            raise DerivedDenied("derived_management_denied")
        self.deadline = min(self.deadline, result.valid_until)

    def require(self, action, resource=None):
        if action not in {"ENTER", "READ_AUDIT", "CLEAR", "REBUILD", "RECONCILE"}:
            raise DerivedDenied("derived_action_invalid")
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
                raise DerivedDenied("derived_resources_unavailable") from exc
            if type(choices) is not tuple or len(choices) > 512:
                raise DerivedDenied("derived_resources_invalid")
            self.choices = set()
            for choice in choices:
                if type(choice) is not tuple or len(choice) != 2 or choice[0] not in catalog.KINDS:
                    raise DerivedDenied("derived_resources_invalid")
                key = choice[0], catalog.uuid_text(choice[1])
                if key in self.choices:
                    raise DerivedDenied("derived_resources_invalid")
                self.choices.add(key)
        return self.choices

    def target(self, kind, identifier):
        if (kind, identifier) not in self.resources():
            raise DerivedDenied("derived_target_outside_mandate")
        target = catalog.target(kind, identifier)
        if target.case_ref not in self.actor.case_keys:
            raise DerivedDenied("derived_case_scope_denied")
        self.targets[kind, identifier] = target
        return target

    def resource(self, target):
        cleared = self.saved.cleared.get((target.kind, target.identifier))
        return dict(
            kind=target.kind,
            id=target.identifier,
            header_digest=target.header_digest,
            case_id=target.case_id,
            case_ref=target.case_ref,
            payload_digest=catalog.digest(target.manifest()),
            payload_count=len(target.payload),
            clearance=catalog.digest(cleared) if cleared else catalog.ZERO,
            state="CLEARED" if cleared else "PRESENT" if target.payload else "ABSENT",
        )

    def callbacks(self):
        for values in self.calls:
            self._call(values)
        self.deadline = min(self.deadline, principals._identity_callbacks(self.principal))

    def final_pins(self):
        selected = policy()
        if selected[0] is not self.selected[0] or selected[1] != self.selected[1]:
            raise DerivedDenied("derived_management_changed")
        principals._identity_pins(self.principal)
        current = store.snapshot(allow_pending=self.allow_pending)
        if (
            current is None
            or current.config != self.saved.config
            or current.events != self.saved.events
            or [store.body(row) for row in current.saved]
            != [store.body(row) for row in self.saved.saved]
        ):
            raise DerivedDenied("derived_ledger_changed")
        for target in self.targets.values():
            if catalog.target(target.kind, target.identifier) != target:
                raise DerivedDenied("derived_payload_changed")
        if set(rebuild_history()) != self.rebuilds:
            raise DerivedDenied("derived_rebuild_history_changed")
        if self.deadline <= timezone.now():
            raise DerivedDenied("derived_management_expired")
        for _, final_pins in self.owner_checks:
            final_pins()

    def finish(self):
        self.callbacks()
        self.verify_owners()
        self.final_pins()

    def cleared(self, value, row, *, appended=True):
        if appended:
            self.saved.events = [*self.saved.events, value]
        self.saved.saved = [*self.saved.saved, row]
        key = value["kind"], value["target_id"]
        self.targets[key] = replace(self.targets[key], payload=())

    def rebuilt(self, row):
        self.rebuilds.add((str(row.pk), row.digest))


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
            guard.final_pins, failure=cases.CaseConflict, code="derived_response_unavailable"
        )
        yield guard
        guard.finish()
