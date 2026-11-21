"""Verified immutable SQL prefix against a separately retained current journal."""

import os
from dataclasses import dataclass

from django.apps import apps
from django.conf import settings
from django.db import connection

from . import catalog
from .catalog import SuppressionDenied
from .journal import LocalJournal

TABLE = "record_suppression_suppressionevent"


def installed():
    return apps.is_installed("apps.record_suppression")


def recorded():
    if installed():
        return apps.get_model("record_suppression.SuppressionEvent").objects.exists()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [TABLE])
        if cursor.fetchone()[0] is None:
            return False
        cursor.execute("SELECT EXISTS(SELECT 1 FROM record_suppression_suppressionevent)")
        return cursor.fetchone()[0]


def configuration():
    return (
        type(getattr(settings, "FATWA_RECORD_SUPPRESSION_ENABLED", False)),
        getattr(settings, "FATWA_RECORD_SUPPRESSION_ENABLED", False),
        getattr(settings, "FATWA_RECORD_SUPPRESSION_JOURNAL", None),
        installed(),
    )


def configured():
    flag = getattr(settings, "FATWA_RECORD_SUPPRESSION_ENABLED", False)
    journal = getattr(settings, "FATWA_RECORD_SUPPRESSION_JOURNAL", None)
    if flag is not True and journal is None and not recorded():
        return None
    if flag is not True or not installed() or os.environ.get("FATWA_PRODUCTION") != "0":
        raise SuppressionDenied("suppression_recorded_policy_required")
    if type(journal) is not LocalJournal:
        raise SuppressionDenied("suppression_current_journal_required")
    return journal


def lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(387,387)")


def body(row):
    value = {}
    for field in catalog.FIELDS:
        current = getattr(row, field)
        if field == "occurred_at":
            current = catalog.stamp(current)
        elif field in {"id", "ledger_id", "target_id", "case_id"}:
            current = str(current) if current is not None else None
        value[field] = current
    return value


def rows():
    if not installed():
        raise SuppressionDenied("suppression_application_required")
    result = list(
        apps.get_model("record_suppression.SuppressionEvent").objects.order_by("sequence")[
            : catalog.LIMIT + 1
        ]
    )
    for row in result:
        value = catalog.body(body(row))
        if (
            row.canonical_payload != catalog.canonical(value)
            or row.digest != catalog.digest(value)
            or row.reason
            and catalog.text_hash(row.reason) != row.reason_sha256
            or not row.recovered
            and not row.reason
        ):
            raise SuppressionDenied("suppression_sql_ledger_changed")
    if result:
        catalog.events([body(row) for row in result], str(result[0].ledger_id))
    return result


@dataclass
class Snapshot:
    journal: LocalJournal
    events: list
    saved: list
    config: tuple

    @property
    def watermark(self):
        return catalog.digest([self.journal.ledger_id, self.events])

    @property
    def heads(self):
        return {(item["target_kind"], item["target_id"]): item for item in self.events}

    def final_pins(self):
        if configuration() != self.config:
            raise SuppressionDenied("suppression_configuration_changed")
        current = snapshot()
        if current is None or current.journal is not self.journal or current.events != self.events:
            raise SuppressionDenied("suppression_decision_changed")


def snapshot(*, allow_pending=False):
    journal = configured()
    if journal is None:
        return None
    decisions, saved = journal.snapshot(), rows()
    sql = [body(row) for row in saved]
    if sql != decisions[: len(sql)] or len(sql) > len(decisions):
        raise SuppressionDenied("suppression_journal_stale_or_changed")
    if not allow_pending and sql != decisions:
        raise SuppressionDenied("suppression_reconciliation_required")
    return Snapshot(journal, decisions, saved, configuration())


def insert(value, *, actor, provider_id, reason="", recovered=False, recovery_reason=""):
    catalog.body(value)
    values = dict(value)
    values["occurred_at"] = catalog.parse_stamp(values["occurred_at"])
    return apps.get_model("record_suppression.SuppressionEvent").objects.create(
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
