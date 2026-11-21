"""A restored SQL prefix must match the independently retained clearance floor."""

import os
from dataclasses import dataclass

from django.apps import apps
from django.conf import settings
from django.db import connection

from . import catalog
from .catalog import DerivedDenied
from .journal import DerivedJournal

TABLE = "derived_maintenance_derivativeclear"


def installed():
    return apps.is_installed("apps.derived_maintenance")


def recorded():
    if installed():
        return apps.get_model("derived_maintenance.DerivativeClear").objects.exists()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [TABLE])
        if cursor.fetchone()[0] is None:
            return False
        cursor.execute("SELECT EXISTS(SELECT 1 FROM derived_maintenance_derivativeclear)")
        return cursor.fetchone()[0]


def configuration():
    return (
        type(getattr(settings, "FATWA_DERIVED_MAINTENANCE_ENABLED", False)),
        getattr(settings, "FATWA_DERIVED_MAINTENANCE_ENABLED", False),
        getattr(settings, "FATWA_DERIVED_MAINTENANCE_JOURNAL", None),
        installed(),
    )


def configured():
    flag = getattr(settings, "FATWA_DERIVED_MAINTENANCE_ENABLED", False)
    journal = getattr(settings, "FATWA_DERIVED_MAINTENANCE_JOURNAL", None)
    if flag is not True and journal is None and not recorded():
        return None
    if flag is not True or not installed() or os.environ.get("FATWA_PRODUCTION") != "0":
        raise DerivedDenied("derived_recorded_policy_required")
    if type(journal) is not DerivedJournal:
        raise DerivedDenied("derived_current_journal_required")
    return journal


def lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(443,509)")


def body(row):
    value = {}
    for name in catalog.FIELDS:
        field = getattr(row, name)
        if name == "occurred_at":
            field = catalog.stamp(field)
        elif name in {"id", "ledger_id", "target_id", "case_id"}:
            field = str(field)
        value[name] = field
    return value


def rows():
    if not installed():
        raise DerivedDenied("derived_application_required")
    values = list(
        apps.get_model("derived_maintenance.DerivativeClear").objects.order_by("sequence")[
            : catalog.LIMIT + 1
        ]
    )
    for row in values:
        value = catalog.body(body(row))
        if (
            row.canonical_payload != catalog.canonical(value)
            or row.digest != catalog.digest(value)
            or row.reason
            and catalog.text_hash(row.reason) != row.reason_sha256
            or not row.recovered
            and not row.reason
        ):
            raise DerivedDenied("derived_sql_ledger_changed")
    if values:
        catalog.events([body(row) for row in values], str(values[0].ledger_id))
    return values


@dataclass
class Snapshot:
    journal: DerivedJournal
    events: list
    saved: list
    config: tuple

    @property
    def watermark(self):
        return catalog.digest([self.journal.ledger_id, self.events])

    @property
    def cleared(self):
        return {(row["kind"], row["target_id"]): row for row in self.events}

    def final_pins(self):
        if configuration() != self.config:
            raise DerivedDenied("derived_configuration_changed")
        current = snapshot()
        if current is None or current.journal is not self.journal or current.events != self.events:
            raise DerivedDenied("derived_clearance_changed")


def snapshot(*, allow_pending=False):
    journal = configured()
    if journal is None:
        return None
    decisions, saved = journal.snapshot(), rows()
    sql = [body(row) for row in saved]
    if sql != decisions[: len(sql)] or len(sql) > len(decisions):
        raise DerivedDenied("derived_journal_stale_or_changed")
    if not allow_pending and sql != decisions:
        raise DerivedDenied("derived_reconciliation_required")
    return Snapshot(journal, decisions, saved, configuration())


def insert(value, *, actor, provider_id, reason="", recovered=False, recovery_reason=""):
    catalog.body(value)
    values = {**value, "occurred_at": catalog.parse_stamp(value["occurred_at"])}
    return apps.get_model("derived_maintenance.DerivativeClear").objects.create(
        **values,
        canonical_payload=catalog.canonical(value),
        digest=catalog.digest(value),
        reason=reason,
        recovered=recovered,
        recovery_reason=recovery_reason,
        applied_provider_id=provider_id,
        applied_subject_id=actor.subject_id,
        applied_role=actor.role,
        applied_auth_epoch=actor.auth_epoch,
    )
