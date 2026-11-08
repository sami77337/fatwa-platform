"""Safe, auditable handling of unknown outcomes in the local synthetic outbox.

A reservation expiring does NOT establish that the provider did not receive it.
Do not retry or reissue the send. Surface the uncertainty, and accept late
provider evidence only through the existing verified receipt path.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
import sqlite3
from pathlib import Path
from typing import Callable

from apps.editorial_export.services import require_development
from .outbox import (
    OutboxConflict, _audit, _db, _now, _read_only_intents, _verified_db,
)

_OPERATOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    intent_key: str
    case_key: str
    provider: str
    answer_revision: int
    part_ordinal: int
    saved_state: str
    attention: str
    reservation_deadline: str | None
    provider_message_id: str | None


def _clock(now: datetime | None) -> datetime:
    stamp = datetime.now(UTC) if now is None else now
    if type(stamp) is not datetime or stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise OutboxConflict("invalid_reconciliation_clock")
    return stamp


def _deadline(row) -> datetime | None:
    raw = row[10]
    if raw is None:
        return None
    if type(raw) is not str:
        raise OutboxConflict("invalid_reservation_deadline")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise OutboxConflict("invalid_reservation_deadline") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise OutboxConflict("invalid_reservation_deadline")
    return parsed


def reconciliation_queue(
    directory: Path, *, now: datetime | None = None, synthetic_fixtures_only: bool = False
) -> tuple[ReconciliationItem, ...]:
    """Read-only review queue; never creates or changes a file."""
    require_development(synthetic_fixtures_only)
    current = _clock(now)
    with _db(directory, writable=False) as con:
        if con is None:
            return ()
        stored, _, _ = _verified_db(con)
        rows = []
        for row in stored.values():
            state = row[8]
            if state == "RESERVED":
                attention = (
                    "UNCERTAIN_RESERVATION_EXPIRED"
                    if (deadline := _deadline(row)) and deadline <= current
                    else "AWAITING_PROVIDER_EVENT"
                )
            elif state == "UNKNOWN_REQUIRES_RECONCILIATION":
                attention = "NEEDS_MANUAL_RECONCILIATION_NO_RETRY"
            elif state == "HELD_FOR_HUMAN":
                attention = "HUMAN_MEDIA_DECISION_REQUIRED"
            elif state in {"QUEUED", "SENT_UNCONFIRMED"}:
                attention = "AWAITING_VERIFIED_DELIVERY"
            elif state == "FAILED_REQUIRES_REVIEW":
                attention = "PROVIDER_REPORTED_FAILURE"
            else:
                continue
            rows.append(ReconciliationItem(
                row[0], row[2], row[3], row[4], row[5], state, attention,
                row[10], row[11],
            ))
        return tuple(sorted(rows, key=lambda r: (r.case_key, r.part_ordinal, r.intent_key)))


def flag_expired_reservations(
    directory: Path, *,
    operator_id: str,
    verify_operator: Callable[[str], bool],
    now: datetime | None = None,
    synthetic_fixtures_only: bool = False,
) -> tuple[str, ...]:
    """Explicitly quarantine expired attempts; never release their idempotency keys.

    This function has no network sender and may only make a send LESS likely.
    It cannot approve a fresh attempt, change a recipient, or claim delivery.
    """
    require_development(synthetic_fixtures_only)
    if (
        type(operator_id) is not str or _OPERATOR.fullmatch(operator_id) is None
        or not callable(verify_operator)
    ):
        raise OutboxConflict("operator_authentication_required")
    try:
        checked = verify_operator(operator_id)
    except Exception as exc:
        raise OutboxConflict("operator_verification_unavailable") from exc
    if checked is not True:
        raise OutboxConflict("operator_not_verified")
    stamp = _clock(now)
    try:
        with _db(directory, writable=False) as con:
            if con is None:
                return ()
        # The writer reservation serializes operator actions and provider
        # receipts. A verified receipt landing first wins and is not overwritten.
        with _db(directory, writable=True) as con:
            stored, _, _ = _verified_db(con)
            changed = []
            for row in sorted(stored.values(), key=lambda r: r[0]):
                if (
                    row[8] != "RESERVED"
                    or (deadline := _deadline(row)) is None
                    or deadline > stamp
                ):
                    continue
                con.execute(
                    "UPDATE intents SET state=?,updated_at=? WHERE intent_key=?",
                    ("UNKNOWN_REQUIRES_RECONCILIATION", _now(), row[0]),
                )
                _audit(
                    con, row[0], "RESERVED", "UNKNOWN_REQUIRES_RECONCILIATION",
                    "operator:" + operator_id,
                )
                changed.append(row[0])
            con.commit()
            return tuple(changed)
    except sqlite3.Error as exc:
        raise OutboxConflict("outbox_reconciliation_unavailable") from exc
