"""Bounded synthetic delivery outbox. No sender, network calls or auto-retry.

The only outward-facing action is a reservation for a trusted adapter to
consume in future integration. Lost/uncertain reservations are NEVER
automatically dispatched again. Real approvals and provider receipts must be
verified by independent adapters supplied by the caller.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from typing import Callable

from apps.editorial_export.services import require_development
from .approval import ApprovalReceipt, CurrentEvidence, require_return_approval
from .planner import InvalidPlan, Plan, Step, receipt_state

FILE_NAME = "synthetic-delivery-outbox.sqlite3"
APP_ID = 0x464F4258  # FOBX
MAX_INTENTS = 128
MAX_EVENTS = 512
_SHA = re.compile(r"^[a-f0-9]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED = frozenset({"STAGED", "HELD_FOR_HUMAN", "RESERVED", "QUEUED",
                      "SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW",
                      "UNKNOWN_REQUIRES_RECONCILIATION"})
_DDL = (
    "CREATE TABLE intents (intent_key TEXT PRIMARY KEY, plan_fingerprint TEXT NOT NULL,"
    "case_key TEXT NOT NULL, provider TEXT NOT NULL, revision INTEGER NOT NULL,"
    "ordinal INTEGER NOT NULL, approval_fingerprint TEXT NOT NULL, action TEXT NOT NULL,"
    "state TEXT NOT NULL, reservation_sha TEXT, reservation_until TEXT,"
    "provider_message_id TEXT, provider_status TEXT, created_at TEXT NOT NULL,"
    "updated_at TEXT NOT NULL) WITHOUT ROWID",
    "CREATE TABLE events (seq INTEGER PRIMARY KEY, intent_key TEXT NOT NULL,"
    "old_state TEXT NOT NULL, new_state TEXT NOT NULL, evidence_ref TEXT NOT NULL,"
    "recorded_at TEXT NOT NULL, previous_digest TEXT NOT NULL,"
    "digest TEXT NOT NULL) WITHOUT ROWID",
    "CREATE TABLE audit_head (id INTEGER PRIMARY KEY, seq INTEGER NOT NULL,"
    "digest TEXT NOT NULL) WITHOUT ROWID",
    "CREATE TRIGGER immutable_outbox_events_update BEFORE UPDATE ON events "
    "BEGIN SELECT RAISE(ABORT,'append_only'); END",
    "CREATE TRIGGER immutable_outbox_events_delete BEFORE DELETE ON events "
    "BEGIN SELECT RAISE(ABORT,'append_only'); END",
)


class OutboxConflict(ValueError):
    """An intent, approval, reservation or receipt conflicts with saved history."""


@dataclass(frozen=True, slots=True)
class StoredIntent:
    intent_key: str
    case_key: str
    provider: str
    revision: int
    ordinal: int
    action: str
    state: str
    provider_message_id: str | None
    reservation_until: str | None


@dataclass(frozen=True, slots=True)
class Reservation:
    intent_key: str
    token: str
    until: str


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    intent_key: str
    provider_message_id: str
    reported: str
    receipt_reference: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _path(directory: Path) -> Path:
    if not isinstance(directory, Path) or directory.is_symlink() or not directory.is_dir():
        raise OutboxConflict("synthetic_outbox_directory_unavailable")
    path = directory.resolve(strict=True) / FILE_NAME
    try:
        info = path.lstat()
    except FileNotFoundError:
        return path
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
        raise OutboxConflict("unsafe_outbox_file")
    return path


def _verified_db(con: sqlite3.Connection) -> tuple[dict, int, str]:
    if con.execute("PRAGMA application_id").fetchone() != (APP_ID,) or (
        con.execute("PRAGMA user_version").fetchone() != (1,)
    ):
        raise OutboxConflict("wrong_outbox_database")
    schema = con.execute(
        "SELECT sql FROM sqlite_schema WHERE type IN ('table','trigger') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if {r[0] for r in schema} != set(_DDL):
        raise OutboxConflict("outbox_schema_mismatch")
    rows = con.execute("SELECT * FROM intents LIMIT ?", (MAX_INTENTS + 1,)).fetchall()
    if len(rows) > MAX_INTENTS:
        raise OutboxConflict("outbox_capacity")
    events = con.execute("SELECT * FROM events ORDER BY seq LIMIT ?", (MAX_EVENTS + 1,)).fetchall()
    if len(events) > MAX_EVENTS:
        raise OutboxConflict("outbox_audit_capacity")
    head = con.execute("SELECT id,seq,digest FROM audit_head LIMIT 2").fetchall()
    if len(head) != 1 or head[0][0] != 1:
        raise OutboxConflict("outbox_audit_head_missing")
    previous = ""
    latest = {}
    for n, event in enumerate(events, 1):
        seq, key, old, new, ref, recorded, old_digest, digest = event
        payload = [seq, key, old, new, ref, recorded]
        expected = sha256((previous + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )).encode()).hexdigest()
        if (
            seq != n or old_digest != previous or digest != expected
            or new not in _ALLOWED or (key in latest and latest[key] != old)
            or (key not in latest and old != "")
        ):
            raise OutboxConflict("outbox_audit_invalid")
        latest[key] = new
        previous = digest
    if (head[0][1], head[0][2]) != (len(events), previous):
        raise OutboxConflict("outbox_audit_tip_mismatch")
    stored = {}
    for row in rows:
        key, fingerprint, case, provider, rev, ordinal, approval, action, state, token, until, message, status, created, updated = row
        if (
            not all(type(v) is str and _SHA.fullmatch(v) for v in (key, fingerprint, approval))
            or type(rev) is not int or rev < 1
            or type(ordinal) is not int or not 1 <= ordinal <= 16
            or state not in _ALLOWED or latest.get(key) != state
            or action not in {"READY_FOR_ADAPTER", "HUMAN_ACTION_REQUIRED", "PUBLISHED_LINK_OPTION"}
            or (action != "READY_FOR_ADAPTER" and state != "HELD_FOR_HUMAN")
            or (token is not None and not _SHA.fullmatch(token))
            or (token is None) != (until is None)
        ):
            raise OutboxConflict("outbox_intent_invalid")
        stored[key] = row
    if len(latest) != len(stored):
        raise OutboxConflict("outbox_missing_intent")
    return stored, len(events), previous


@contextmanager
def _db(directory: Path, *, writable: bool):
    path = _path(directory)
    if not writable and not path.exists():
        yield None
        return
    con = sqlite3.connect(
        path.as_uri() + ("?mode=rwc" if writable else "?mode=ro"),
        isolation_level=None, uri=True, timeout=5,
    )
    try:
        con.execute("PRAGMA trusted_schema=OFF")
        if writable:
            con.execute("PRAGMA synchronous=FULL")
        con.execute("BEGIN IMMEDIATE" if writable else "BEGIN")
        if writable and con.execute("PRAGMA application_id").fetchone() == (0,):
            # A new file must also have no existing tables.
            if con.execute("SELECT count(*) FROM sqlite_schema").fetchone() != (0,):
                raise OutboxConflict("unrecognized_outbox_file")
            con.execute(f"PRAGMA application_id={APP_ID}")
            con.execute("PRAGMA user_version=1")
            for ddl in _DDL:
                con.execute(ddl)
            con.execute("INSERT INTO audit_head VALUES (1,0,'')")
        yield con
    finally:
        con.close()


def _audit(con, key: str, old: str, new: str, ref: str):
    seq, previous = con.execute("SELECT seq,digest FROM audit_head WHERE id=1").fetchone()
    if seq >= MAX_EVENTS:
        raise OutboxConflict("outbox_audit_capacity")
    stamp = _now()
    payload = [seq + 1, key, old, new, ref, stamp]
    digest = sha256((previous + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))).encode()).hexdigest()
    con.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (*payload, previous, digest))
    con.execute("UPDATE audit_head SET seq=?,digest=? WHERE id=1", (seq + 1, digest))


def _plan_fingerprint(plan: Plan) -> str:
    return sha256(json.dumps(
        asdict(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _approval(plan, approval, evidence, verify_approval):
    return require_return_approval(
        receipt=approval, evidence=evidence, plan=plan, verify_receipt=verify_approval
    )


def _read_only_intents(rows) -> tuple[StoredIntent, ...]:
    return tuple(StoredIntent(
        r[0], r[2], r[3], r[4], r[5], r[7], r[8], r[11], r[10]
    ) for r in rows)


def list_intents(directory: Path, *, synthetic_fixtures_only: bool = False) -> tuple[StoredIntent, ...]:
    require_development(synthetic_fixtures_only)
    with _db(directory, writable=False) as con:
        if con is None:
            return ()
        stored, _, _ = _verified_db(con)
        return _read_only_intents(stored.values())


def stage_plan(
    directory: Path, *,
    plan: Plan, approval: ApprovalReceipt, evidence: CurrentEvidence,
    verify_approval: Callable[[ApprovalReceipt], bool],
    synthetic_fixtures_only: bool = False,
) -> tuple[StoredIntent, ...]:
    """Store approved intent metadata only. Nothing is dispatched."""
    require_development(synthetic_fixtures_only)
    bound = _approval(plan, approval, evidence, verify_approval)
    if not isinstance(plan, Plan) or not 1 <= len(plan.steps) <= 16:
        raise InvalidPlan("invalid_outbox_plan")
    expected_status = (
        "REQUIRES_HUMAN_DECISION"
        if any(step.action != "READY_FOR_ADAPTER" for step in plan.steps)
        else "PLANNED_NOT_SENT"
    )
    if plan.status != expected_status:
        raise InvalidPlan("invalid_plan_status")
    for ordinal, step in enumerate(plan.steps, 1):
        if (
            not isinstance(step, Step) or type(step.ordinal) is not int
            or step.ordinal != ordinal or type(step.idempotency_key) is not str
            or _SHA.fullmatch(step.idempotency_key) is None
            or step.action not in {
                "READY_FOR_ADAPTER", "HUMAN_ACTION_REQUIRED", "PUBLISHED_LINK_OPTION"
            }
        ):
            raise InvalidPlan("invalid_plan_step")
    fingerprint = _plan_fingerprint(plan)
    try:
        with _db(directory, writable=True) as con:
            stored, _, _ = _verified_db(con)
            for step in plan.steps:
                desired = "STAGED" if step.action == "READY_FOR_ADAPTER" else "HELD_FOR_HUMAN"
                row = stored.get(step.idempotency_key)
                if row:
                    if (
                        row[1], row[2], row[3], row[4], row[5], row[6], row[7]
                    ) != (
                        fingerprint, plan.case_key, plan.source_provider,
                        plan.answer_revision, step.ordinal, bound.approval_fingerprint, step.action
                    ):
                        raise OutboxConflict("intent_identity_collision_or_changed_approval")
                    continue
                if len(stored) >= MAX_INTENTS:
                    raise OutboxConflict("outbox_capacity")
                stamp = _now()
                con.execute(
                    "INSERT INTO intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        step.idempotency_key, fingerprint, plan.case_key, plan.source_provider,
                        plan.answer_revision, step.ordinal, bound.approval_fingerprint,
                        step.action, desired, None, None, None, None, stamp, stamp,
                    ),
                )
                _audit(con, step.idempotency_key, "", desired, bound.receipt_id)
                stored[step.idempotency_key] = con.execute(
                    "SELECT * FROM intents WHERE intent_key=?", (step.idempotency_key,)
                ).fetchone()
            con.commit()
            return _read_only_intents(stored[step.idempotency_key] for step in plan.steps)
    except sqlite3.Error as exc:
        raise OutboxConflict("outbox_store_unavailable") from exc


def reserve_for_adapter(
    directory: Path, *, intent_key: str, plan: Plan, approval: ApprovalReceipt,
    evidence: CurrentEvidence, verify_approval: Callable[[ApprovalReceipt], bool],
    ttl_seconds: int = 60, synthetic_fixtures_only: bool = False,
) -> Reservation:
    """Reserve one send attempt; never retry automatically after an uncertain outcome."""
    require_development(synthetic_fixtures_only)
    bound = _approval(plan, approval, evidence, verify_approval)
    if type(ttl_seconds) is not int or not 5 <= ttl_seconds <= 300:
        raise OutboxConflict("invalid_reservation_ttl")
    if type(intent_key) is not str or _SHA.fullmatch(intent_key) is None:
        raise OutboxConflict("invalid_intent_key")
    if intent_key not in {s.idempotency_key for s in plan.steps}:
        raise OutboxConflict("intent_not_in_verified_plan")
    try:
        with _db(directory, writable=True) as con:
            stored, _, _ = _verified_db(con)
            row = stored.get(intent_key)
            if (
                row is None or row[1] != _plan_fingerprint(plan)
                or row[6] != bound.approval_fingerprint
                or row[7] != "READY_FOR_ADAPTER"
                or row[8] != "STAGED"
            ):
                raise OutboxConflict("intent_not_reservable")
            token = secrets.token_urlsafe(32)
            until = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(
                timespec="microseconds"
            )
            con.execute(
                "UPDATE intents SET state='RESERVED',reservation_sha=?,"
                "reservation_until=?,updated_at=? WHERE intent_key=?",
                (sha256(token.encode()).hexdigest(), until, _now(), intent_key),
            )
            _audit(con, intent_key, "STAGED", "RESERVED", "reservation-created")
            con.commit()
            return Reservation(intent_key, token, until)
    except sqlite3.Error as exc:
        raise OutboxConflict("outbox_store_unavailable") from exc


def record_provider_receipt(
    directory: Path, *, reservation: Reservation, receipt: ProviderReceipt,
    verify_provider_receipt: Callable[[ProviderReceipt], bool],
    synthetic_fixtures_only: bool = False,
) -> StoredIntent:
    """Reconcile one verified provider event. Accepted != delivered."""
    require_development(synthetic_fixtures_only)
    if (
        not isinstance(reservation, Reservation)
        or not isinstance(receipt, ProviderReceipt)
        or reservation.intent_key != receipt.intent_key
        or type(reservation.token) is not str
        or not all(_REF.fullmatch(value) is not None and type(value) is str for value in (
            receipt.provider_message_id, receipt.receipt_reference
        ))
        or receipt.reported not in {"QUEUED", "ACCEPTED", "DELIVERED", "FAILED"}
        or not callable(verify_provider_receipt)
    ):
        raise OutboxConflict("invalid_provider_receipt")
    try:
        verified = verify_provider_receipt(receipt)
    except Exception as exc:
        raise OutboxConflict("provider_receipt_verifier_unavailable") from exc
    if verified is not True:
        raise OutboxConflict("provider_receipt_unverified")
    try:
        with _db(directory, writable=True) as con:
            stored, _, _ = _verified_db(con)
            row = stored.get(receipt.intent_key)
            if (
                row is None or row[9] is None
                or not compare_digest(row[9], sha256(reservation.token.encode()).hexdigest())
                or row[7] != "READY_FOR_ADAPTER"
            ):
                raise OutboxConflict("receipt_reservation_mismatch")
            action = Step(row[5], row[7], "", row[0])
            state = receipt_state(
                planned_step=action, verified_adapter_receipt=True, reported=receipt.reported
            )
            old = row[8]
            if row[11] is not None and row[11] != receipt.provider_message_id:
                raise OutboxConflict("multiple_provider_message_ids")
            if old == state and row[12] == receipt.reported:
                return _read_only_intents((row,))[0]
            allowed = {
                "RESERVED": {"QUEUED", "SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW"},
                "QUEUED": {"SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW"},
                "SENT_UNCONFIRMED": {"DELIVERED", "FAILED_REQUIRES_REVIEW"},
                # An expired reservation is not permission to send again. A
                # verified late receipt may still establish what actually happened.
                "UNKNOWN_REQUIRES_RECONCILIATION": {"SENT_UNCONFIRMED", "DELIVERED", "FAILED_REQUIRES_REVIEW"},
            }
            if state not in allowed.get(old, set()):
                raise OutboxConflict("provider_receipt_invalid_transition")
            con.execute(
                "UPDATE intents SET state=?,provider_message_id=?,provider_status=?,updated_at=?"
                " WHERE intent_key=?",
                (state, receipt.provider_message_id, receipt.reported, _now(), receipt.intent_key),
            )
            _audit(con, receipt.intent_key, old, state, receipt.receipt_reference)
            con.commit()
            return _read_only_intents(
                (con.execute("SELECT * FROM intents WHERE intent_key=?", (receipt.intent_key,)).fetchone(),)
            )[0]
    except sqlite3.Error as exc:
        raise OutboxConflict("outbox_store_unavailable") from exc
