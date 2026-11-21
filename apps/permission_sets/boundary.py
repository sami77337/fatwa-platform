"""Explicit administrative mandates and final pure pins around preview, save and HTML."""

import json
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
from .authority import Grant, PermissionManagementAuthority
from .catalog import PermissionDenied


def policy():
    store.enabled()
    authority = getattr(settings, "FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY", None)
    if not isinstance(authority, PermissionManagementAuthority):
        raise PermissionDenied("permission_management_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise PermissionDenied("permission_management_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise PermissionDenied("permission_management_snapshot_required")
    return authority, epoch


class Guard:
    def __init__(self, provider, subject_id, session_deadline):
        self.selected = policy()
        self.provider = provider
        actor = identity.validate(provider.resolve(subject_id), subject_id=subject_id)
        if actor.role not in {"MUFTI", "ORGANIZER_ADMIN"}:
            raise PermissionDenied("permission_administrative_role_required")
        self.principal = principals.staff_principal(provider, actor)
        self.actor, self.provider_id = actor, self.principal.provider_id
        self.deadline = self.principal.valid_until
        if session_deadline is not None:
            if not identity.valid_deadline(session_deadline):
                raise PermissionDenied("permission_session_expired")
            self.deadline = min(self.deadline, session_deadline)
        self.calls, self.targets, self.sources = [], {}, {}
        self.saved = store.rows()
        self.watermark = store.fingerprint(self.saved)
        self.subject_ids = None
        self.resources = None

    def require(self, operation, kind="", key="", *, target=None, resource=None):
        values = {
            "provider_id": self.provider_id,
            "subject_id": self.actor.subject_id,
            "auth_epoch": self.actor.auth_epoch,
            "role": self.actor.role,
            "operation": operation,
            "scope_kind": kind,
            "scope_key": key,
            "target_subject": target.subject_id if target else "",
            "target_role": target.role if target else "",
            "resource": resource,
        }
        self._call(values)
        self.calls.append(values)

    def _call(self, values):
        try:
            grant = self.selected[0].authorize(
                **{
                    **values,
                    "resource": None
                    if values["resource"] is None
                    else json.loads(catalog.canonical(values["resource"])),
                }
            )
        except Exception as exc:
            raise PermissionDenied("permission_management_denied") from exc
        if type(grant) is not Grant or not identity.valid_deadline(grant.valid_until):
            raise PermissionDenied("permission_management_denied")
        self.deadline = min(self.deadline, grant.valid_until)

    def candidates(self):
        if self.subject_ids is not None:
            return self.subject_ids
        try:
            values = self.selected[0].subjects(
                provider_id=self.provider_id,
                subject_id=self.actor.subject_id,
                auth_epoch=self.actor.auth_epoch,
                role=self.actor.role,
            )
        except Exception as exc:
            raise PermissionDenied("permission_candidates_unavailable") from exc
        if type(values) is not tuple or len(values) > catalog.MAX_CANDIDATES:
            raise PermissionDenied("permission_candidates_invalid")
        values = tuple(catalog.identifier(value) for value in values)
        if len(set(values)) != len(values):
            raise PermissionDenied("permission_candidates_invalid")
        self.subject_ids = values
        return values

    def target(self, subject_id, *, changing=False):
        catalog.identifier(subject_id)
        if subject_id not in self.candidates() or changing and subject_id == self.actor.subject_id:
            raise PermissionDenied("permission_target_denied")
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if subject_id not in self.targets:
            actor = identity.resolve(directory, subject_id)
            self.targets[subject_id] = principals.staff_principal(directory, actor)
            self.deadline = min(self.deadline, self.targets[subject_id].valid_until)
        return self.targets[subject_id].actor

    def choices(self):
        if self.resources is not None:
            return self.resources
        try:
            values = self.selected[0].resources(
                provider_id=self.provider_id,
                subject_id=self.actor.subject_id,
                auth_epoch=self.actor.auth_epoch,
                role=self.actor.role,
            )
        except Exception as exc:
            raise PermissionDenied("permission_resources_unavailable") from exc
        if type(values) is not tuple or len(values) > catalog.MAX_RESOURCES:
            raise PermissionDenied("permission_resources_invalid")
        self.resources = {}
        for value in values:
            value = catalog.scope(value)
            self.source(value)
            key = catalog.digest(value)
            if key in self.resources:
                raise PermissionDenied("permission_resources_invalid")
            self.resources[key] = value
        return self.resources

    def source(self, value, target=None):
        refs = catalog.verify_scope(value)
        if not refs <= self.actor.case_keys or target and not refs <= target.case_keys:
            raise PermissionDenied("permission_scope_denied")
        self.sources[catalog.digest(value)] = value

    def manage_rule(self, rule, kind, key, target=None):
        rule = catalog.rule(rule)
        self.source(rule["scope"], target)
        if catalog.digest(rule["scope"]) not in self.choices():
            raise PermissionDenied("permission_rule_outside_mandate")
        self.require("MANAGE_RULE", kind, key, target=target, resource=rule)

    def account(self, row):
        # Account for this exact append only; never adopt a fresh ledger after a
        # callback, which could conceal an unrelated administrative mutation.
        store.verify(row)
        self.saved.append(row)
        self.saved.sort(
            key=lambda value: (value.kind, value.provider_id, value.scope_key, value.number)
        )
        self.watermark = store.fingerprint(self.saved)

    def callbacks(self):
        for value in self.calls:
            self._call(value)
        for principal in (self.principal, *self.targets.values()):
            self.deadline = min(self.deadline, principals._identity_callbacks(principal))

    def final_pins(self):
        selected = policy()
        if selected[0] is not self.selected[0] or selected[1] != self.selected[1]:
            raise PermissionDenied("permission_management_changed")
        for principal in (self.principal, *self.targets.values()):
            principals._identity_pins(principal)
        if store.fingerprint() != self.watermark:
            raise PermissionDenied("permission_ledger_changed")
        for value in self.sources.values():
            if not catalog.verify_scope(value) <= self.actor.case_keys:
                raise PermissionDenied("permission_source_changed")
        if self.deadline <= timezone.now():
            raise PermissionDenied("permission_management_expired")

    def finish(self):
        self.callbacks()
        self.final_pins()


@mutation_context
@contextmanager
def scope(*, provider, subject_id, synthetic_fixtures_only=False, session_deadline=None):
    cases._guard(synthetic_fixtures_only)
    policy()
    with synthetic_queue_atomic(), transaction.atomic():
        # Same canonical graph order as the operational sources. This precedes
        # the permission ledger lock even when a source is shared by two cases.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        store.lock()
        guard = Guard(provider, subject_id, session_deadline)
        guard.require("ENTER")
        guard.final_pins()
        yield guard
        guard.finish()
