"""Transactional local journal for the fixed synthetic case-source history."""

import json
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from itertools import groupby
from pathlib import Path

from apps.editorial_export.services import require_development

from . import clarifications as clar
from .draft_source_review import inspect_draft_source
from .source_history import SourceEvent, replay_source_history, source_receipt, validate_event_shape

JOURNAL_FILENAME = "synthetic-source-history.sqlite3"
_APP_ID = 0x46534A31  # FSJ1
_MAX_FILE = 4 * 1024 * 1024
_MAX_ROWS = 3 * 128  # Three fixed cases with at most 128 accepted events each.
_SCHEMA = {
    "source_events": "CREATE TABLE source_events (case_key TEXT NOT NULL, seq INTEGER NOT NULL, "
    "payload BLOB NOT NULL, digest TEXT NOT NULL, PRIMARY KEY (case_key, seq)) WITHOUT ROWID",
    "source_heads": "CREATE TABLE source_heads (case_key TEXT PRIMARY KEY, seq INTEGER NOT NULL, "
    "digest TEXT NOT NULL) WITHOUT ROWID",
}
_SCHEMA["prevent_source_replace"] = (
    "CREATE TRIGGER prevent_source_replace BEFORE INSERT ON source_events "
    "WHEN EXISTS (SELECT 1 FROM source_events WHERE case_key=NEW.case_key AND seq=NEW.seq) "
    "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
)
for _operation in ("UPDATE", "DELETE"):
    _name = "prevent_source_" + _operation.lower()
    _SCHEMA[_name] = (
        f"CREATE TRIGGER {_name} BEFORE {_operation} ON source_events "
        "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
    )


_REVIEW_CASE = "intake-7"
_REVIEWER = "synthetic-reviewer"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REVIEW_SCHEMA = {
    "source_reviews": "CREATE TABLE source_reviews (case_key TEXT NOT NULL, draft_revision INTEGER NOT NULL, "
    "reviewer TEXT NOT NULL, count INTEGER NOT NULL, source_digest TEXT NOT NULL, "
    "draft_digest TEXT NOT NULL, recorded_at TEXT NOT NULL, "
    "PRIMARY KEY(case_key,draft_revision,reviewer,count,draft_digest)) WITHOUT ROWID",
    "prevent_review_replace": "CREATE TRIGGER prevent_review_replace BEFORE INSERT ON source_reviews "
    "WHEN EXISTS (SELECT 1 FROM source_reviews WHERE case_key=NEW.case_key AND "
    "draft_revision=NEW.draft_revision AND reviewer=NEW.reviewer AND count=NEW.count AND "
    "draft_digest=NEW.draft_digest) BEGIN SELECT RAISE(ABORT, 'append_only'); END",
}
for _operation in ("UPDATE", "DELETE"):
    _name = "prevent_review_" + _operation.lower()
    _REVIEW_SCHEMA[_name] = (
        f"CREATE TRIGGER {_name} BEFORE {_operation} ON source_reviews "
        "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
    )


class ReviewConflict(ValueError):
    """The supplied snapshot is no longer the current reviewable version."""


@dataclass(frozen=True, slots=True)
class ReviewReceipt:
    reviewer: str
    count: int
    source_digest: str
    draft_digest: str
    recorded_at: str
    reply_digest: str = ""


@dataclass(frozen=True, slots=True)
class CaseReview:
    events: tuple[SourceEvent, ...]
    receipt: ReviewReceipt | None
    clarifications: tuple[clar.ClarificationEvent, ...] = ()

    @property
    def thread_digest(self):
        return self.clarifications[-1].digest if self.clarifications else ""

    @property
    def reply_digest(self):
        return clar.last_reply_digest(self.clarifications)


class JournalError(ValueError):
    """The requested synthetic journal could not be opened or verified."""


def _path(directory: Path) -> Path:
    if not isinstance(directory, Path) or directory.is_symlink() or not directory.is_dir():
        raise JournalError("journal_directory_unavailable")
    return directory.resolve(strict=True) / JOURNAL_FILENAME


def _exists(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    # SQLite can open/unlink these names independently. The store uses DELETE-mode journals.
    for suffix in ("-journal", "-wal", "-shm"):
        try:
            sidecar = path.with_name(path.name + suffix).lstat()
        except FileNotFoundError:
            continue
        if (
            suffix != "-journal"
            or not stat.S_ISREG(sidecar.st_mode)
            or sidecar.st_nlink != 1
            or sidecar.st_size > 2 * _MAX_FILE
        ):
            raise JournalError("unexpected_journal_sidecar")
        if info is None:
            # A concurrent bootstrap may have published the DB after our first lstat.
            try:
                info = path.lstat()
            except FileNotFoundError as exc:
                raise JournalError("orphaned_journal_sidecar") from exc
    if info is None:
        return False
    if not stat.S_ISREG(info.st_mode) or not 100 <= info.st_size <= _MAX_FILE:
        raise JournalError("unexpected_journal_file")
    # Closing a raw OS fd can drop another sqlite3 connection's POSIX locks.
    # Use SQLite's VFS for the header probe too. Immutable read-only mode
    # avoids recovering an unknown DB or making WAL/SHM files. Its reported
    # journal_mode is unreliable here; inspect only the fixed format bytes
    # from the bounded image, never use this unlocked view for event data.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as probe:
        if probe.execute("PRAGMA application_id").fetchone() != (_APP_ID,):
            raise JournalError("unexpected_journal_file")
        (page_size,) = probe.execute("PRAGMA page_size").fetchone()
        (pages,) = probe.execute("PRAGMA page_count").fetchone()
        if not (512 <= page_size <= 65536 and 1 <= pages <= _MAX_FILE // page_size):
            raise JournalError("unexpected_journal_file")
        if probe.serialize()[18:20] != b"\x01\x01":
            raise JournalError("unexpected_journal_file")
    return True


def _initialize(path: Path) -> None:
    # Build the complete schema privately, then publish it without replacing another writer's file.
    fd, tmp = tempfile.mkstemp(prefix=".synthetic-source-", dir=path.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(tmp, isolation_level=None)) as con:
            con.execute("PRAGMA synchronous=FULL")
            con.execute("BEGIN IMMEDIATE")
            con.execute(f"PRAGMA application_id={_APP_ID}")
            con.execute("PRAGMA user_version=1")
            for sql in _SCHEMA.values():
                con.execute(sql)
            con.commit()
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(tmp)


def _encode(event: SourceEvent) -> bytes:
    obj = asdict(event)
    obj["body_utf8"] = event.body_utf8.decode("utf-8") if event.body_utf8 is not None else None
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(previous: str, payload: bytes) -> str:
    return sha256(bytes.fromhex(previous) + payload).hexdigest()


def history_digest(history: tuple[SourceEvent, ...]) -> str | None:
    """Return the journal tip of a previously validated full history or prefix."""
    tip = ""
    for event in history:
        tip = _digest(tip, _encode(event))
    return tip or None


def _verified(con: sqlite3.Connection):
    (version,) = con.execute("PRAGMA user_version").fetchone()
    expected = _SCHEMA | _REVIEW_SCHEMA if version >= 2 else _SCHEMA
    if version == 3:
        expected |= clar.SCHEMA
    entries = con.execute(
        "SELECT name,sql FROM sqlite_schema LIMIT ?", (len(expected) + 1,)
    ).fetchall()
    if (
        version not in (1, 2, 3)
        or len(entries) != len(expected)
        or dict(entries) != expected
        or con.execute("PRAGMA application_id").fetchone() != (_APP_ID,)
    ):
        raise JournalError("journal_schema_mismatch")
    histories, heads = {}, {}
    rows = con.execute(
        "SELECT case_key,seq,payload,digest FROM source_events ORDER BY case_key,seq LIMIT ?",
        (_MAX_ROWS + 1,),
    ).fetchall()
    if len(rows) > _MAX_ROWS:
        raise JournalError("journal_capacity_exceeded")
    try:
        for key, group in groupby(rows, lambda r: r[0]):
            events = []
            previous = ""
            for expected, (_, seq, payload, digest) in enumerate(group, 1):
                if (
                    type(payload) is not bytes
                    or seq != expected
                    or _digest(previous, payload) != digest
                ):
                    raise JournalError("journal_record_mismatch")
                obj = json.loads(payload)
                if obj["body_utf8"] is not None:
                    obj["body_utf8"] = obj["body_utf8"].encode()
                event = SourceEvent(**obj)
                if event.case_key != key or _encode(event) != payload:
                    raise JournalError("journal_payload_mismatch")
                events.append(event)
                previous = digest
            history = replay_source_history(events, synthetic_fixtures_only=True)
            if tuple(events) != history:
                raise JournalError("journal_duplicate_record")
            histories[key] = history
            heads[key] = (len(history), previous)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise JournalError("journal_history_invalid") from exc
    stored_heads = {
        key: (n, tip) for key, n, tip in con.execute("SELECT * FROM source_heads LIMIT 4")
    }
    if stored_heads != heads:
        raise JournalError("journal_head_mismatch")
    thread = ()
    if version == 3:
        try:
            thread = clar.read_thread(con)
        except (ValueError, TypeError) as exc:
            raise JournalError("journal_clarification_invalid") from exc
    reply_numbers = {e.digest: e.number for e in thread if e.kind == "reply"}
    receipts = []
    if version >= 2:
        select_reviews = (
            "SELECT case_key,draft_revision,reviewer,count,source_digest,draft_digest,recorded_at,"
            "'' AS reply_digest FROM source_reviews"
        )
        if version == 3:
            select_reviews += (
                " UNION ALL SELECT 'intake-7',1,reviewer,count,source_digest,draft_digest,"
                "recorded_at,reply_digest FROM clarified_reviews"
            )
        limit = 128 if version == 2 else 192
        rows = con.execute(
            f"SELECT r.*,e.digest FROM ({select_reviews}) r LEFT JOIN source_events e ON "
            "e.case_key=r.case_key AND e.seq=r.count LIMIT ?",
            (limit + 1,),
        ).fetchall()
        if not 1 <= len(rows) <= limit:
            raise JournalError("journal_review_count_invalid")
        for case_key, rev, actor, count, source, draft, recorded, reply, event_digest in rows:
            if (
                case_key != _REVIEW_CASE
                or rev != 1
                or actor != _REVIEWER
                or source != event_digest
                or type(draft) is not str
                or not _DIGEST.fullmatch(draft)
                or not clar.valid_timestamp(recorded)
                or (
                    reply != ""
                    and (
                        reply not in reply_numbers
                        or thread[reply_numbers[reply] - 1].source_count > count
                    )
                )
            ):
                raise JournalError("journal_review_invalid")
            receipts.append(ReviewReceipt(actor, count, source, draft, recorded, reply))
        receipts.sort(key=lambda r: (r.count, reply_numbers.get(r.reply_digest, 0), r.recorded_at))
        # A request can only originate from a reading of all evidence present at that point.
        reads = {(r.count, r.source_digest, r.draft_digest, r.reply_digest) for r in receipts}
        reply = ""
        for turn in thread:
            if turn.kind == "reply":
                reply = turn.digest
            elif (turn.source_count, turn.source_digest, turn.draft_digest, reply) not in reads:
                raise JournalError("clarification_request_without_reading")
    return histories, heads, receipts, thread


def _connect(path: Path, writable: bool) -> sqlite3.Connection:
    mode = "rw" if writable else "ro"
    con = sqlite3.connect(
        path.as_uri() + "?mode=" + mode, uri=True, isolation_level=None, timeout=5
    )
    try:
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16 * 1024)
        con.execute("PRAGMA trusted_schema=OFF")
        if writable:
            con.execute("PRAGMA synchronous=FULL")
        con.execute("BEGIN IMMEDIATE" if writable else "BEGIN")
        return con
    except sqlite3.Error:
        con.close()
        raise


def _read_state(directory, case_key, synthetic_fixtures_only):
    require_development(synthetic_fixtures_only)
    source_receipt(case_key)
    try:
        path = _path(directory)
        if not _exists(path):
            return CaseReview((), None)
        with closing(_connect(path, False)) as con:
            histories, _, receipts, thread = _verified(con)
            events = histories.get(case_key, ())
            if case_key != _REVIEW_CASE:
                return CaseReview(events, None)
            return CaseReview(events, receipts[-1] if receipts else None, thread)
    except (OSError, sqlite3.Error) as exc:
        raise JournalError("journal_read_unavailable") from exc


def read_source_history(
    directory: Path, case_key: str, *, synthetic_fixtures_only: bool = False
) -> tuple[SourceEvent, ...]:
    """Read a verified committed snapshot; an absent case/file returns an empty tuple."""
    return _read_state(directory, case_key, synthetic_fixtures_only).events


def read_review_state(
    directory: Path, *, synthetic_fixtures_only: bool = False
) -> tuple[tuple[SourceEvent, ...], ReviewReceipt | None]:
    """Read the fixed case and its last recorded review from the same transaction."""
    state = read_case_review(directory, synthetic_fixtures_only=synthetic_fixtures_only)
    return state.events, state.receipt


def read_case_review(directory: Path, *, synthetic_fixtures_only: bool = False) -> CaseReview:
    """Read the source, latest reading and clarification thread in one snapshot."""
    return _read_state(directory, _REVIEW_CASE, synthetic_fixtures_only)


@contextmanager
def _locked_case(directory, reviewer, count, source_digest, draft_digest):
    """Validate the caller-supplied source and draft while holding the writer reservation."""
    if type(reviewer) is not str or reviewer != _REVIEWER:
        raise ValueError("unknown_synthetic_reviewer")
    if (
        type(count) is not int
        or not 1 <= count <= 128
        or type(source_digest) is not str
        or not _DIGEST.fullmatch(source_digest)
        or type(draft_digest) is not str
        or not _DIGEST.fullmatch(draft_digest)
    ):
        raise ValueError("invalid_review_version")
    try:
        path = _path(directory)
        if not _exists(path):
            raise ReviewConflict("source_history_missing")
        with closing(_connect(path, True)) as con:
            histories, heads, receipts, thread = _verified(con)
            if heads.get(_REVIEW_CASE) != (count, source_digest):
                raise ReviewConflict("source_version_changed")
            obs = inspect_draft_source(
                _REVIEW_CASE, 1, histories[_REVIEW_CASE], synthetic_fixtures_only=True
            )
            if obs.draft_revision_sha256 != draft_digest:
                raise ReviewConflict("draft_version_changed")
            yield con, receipts, thread
    except (OSError, sqlite3.Error) as exc:
        raise JournalError("journal_write_unavailable") from exc


def acknowledge_review(
    directory: Path,
    *,
    reviewer: str,
    count: int,
    source_digest: str,
    draft_digest: str,
    reply_digest: str = "",
    synthetic_fixtures_only: bool = False,
) -> ReviewReceipt:
    """Save a reading of the source, draft and most recent received clarification together."""
    require_development(synthetic_fixtures_only)
    with _locked_case(directory, reviewer, count, source_digest, draft_digest) as (
        con,
        receipts,
        thread,
    ):
        if reply_digest != clar.last_reply_digest(thread):
            raise ReviewConflict("clarification_evidence_changed")
        for receipt in receipts:
            if (receipt.count, receipt.draft_digest, receipt.reply_digest) == (
                count,
                draft_digest,
                reply_digest,
            ):
                return receipt
        if len(receipts) >= (192 if thread else 128):
            raise JournalError("journal_review_capacity_exceeded")
        if not receipts:
            for sql in _REVIEW_SCHEMA.values():
                con.execute(sql)
            con.execute("PRAGMA user_version=2")
        stamp = datetime.now(UTC).isoformat(timespec="microseconds")
        if reply_digest:
            con.execute(
                "INSERT INTO clarified_reviews VALUES (?,?,?,?,?,?)",
                (count, source_digest, draft_digest, reply_digest, stamp, reviewer),
            )
        else:
            con.execute(
                "INSERT INTO source_reviews VALUES (?,?,?,?,?,?,?)",
                (_REVIEW_CASE, 1, reviewer, count, source_digest, draft_digest, stamp),
            )
        con.commit()
        return ReviewReceipt(reviewer, count, source_digest, draft_digest, stamp, reply_digest)


def record_clarification(
    directory: Path,
    *,
    reviewer: str,
    count: int,
    source_digest: str,
    draft_digest: str,
    thread_digest: str,
    kind: str,
    value: str,
    synthetic_fixtures_only: bool = False,
) -> clar.ClarificationEvent:
    """Append one operator action, rejecting an obsolete source, draft or conversation."""
    require_development(synthetic_fixtures_only)
    clar.validate_value(kind, value)
    if type(thread_digest) is not str or (thread_digest and not _DIGEST.fullmatch(thread_digest)):
        raise clar.ClarificationInput("invalid_clarification_version")
    with _locked_case(directory, reviewer, count, source_digest, draft_digest) as (
        con,
        receipts,
        thread,
    ):
        last = thread[-1] if thread else None
        if thread_digest != (last.digest if last else ""):
            # An identical resubmission of the immediately preceding form has no second effect.
            if (
                last
                and thread_digest == (thread[-2].digest if len(thread) > 1 else "")
                and (last.kind, last.text, last.source_digest, last.draft_digest)
                == (kind, value, source_digest, draft_digest)
            ):
                return last
            raise ReviewConflict("clarification_thread_changed")
        expected_kind = "reply" if last and last.kind == "request" else "request"
        if kind != expected_kind:
            raise ReviewConflict("clarification_state_changed")
        if len(thread) >= clar.MAX_TURNS:
            raise clar.ClarificationInput("clarification_capacity_exceeded")
        if kind == "request":
            receipt = receipts[-1] if receipts else None
            if receipt is None or (receipt.count, receipt.draft_digest, receipt.reply_digest) != (
                count,
                draft_digest,
                clar.last_reply_digest(thread),
            ):
                raise ReviewConflict("review_current_evidence_before_request")
        if not thread:
            for sql in clar.SCHEMA.values():
                con.execute(sql)
            con.execute("PRAGMA user_version=3")
        number = len(thread) + 1
        stamp = datetime.now(UTC).isoformat(timespec="microseconds")
        digest = clar.turn_digest(
            thread_digest, number, kind, value, stamp, count, source_digest, draft_digest
        )
        con.execute(
            "INSERT INTO clarification_turns VALUES (?,?,?,?,?,?,?,?)",
            (number, kind, value, stamp, count, source_digest, draft_digest, digest),
        )
        con.execute(
            "INSERT INTO clarification_head VALUES (?,?,?) ON CONFLICT(case_key) DO UPDATE SET "
            "number=excluded.number,digest=excluded.digest",
            (_REVIEW_CASE, number, digest),
        )
        con.commit()
        return clar.ClarificationEvent(
            number, kind, value, stamp, digest, count, source_digest, draft_digest
        )


def append_source_event(
    directory: Path, event: SourceEvent, *, synthetic_fixtures_only: bool = False
) -> tuple[SourceEvent, ...]:
    """Append one validated change or replay one identical prior event without writing again."""
    require_development(synthetic_fixtures_only)
    validate_event_shape(event)
    try:
        path = _path(directory)
        if not _exists(path):
            replay_source_history([event], synthetic_fixtures_only=True)
            _initialize(path)
            _exists(path)
        with closing(_connect(path, True)) as con:
            histories, heads, _, _ = _verified(con)
            old = histories.get(event.case_key, ())
            # Validate retries even at capacity without adding a 129th replay element.
            prior = next((e for e in old if e.event_id == event.event_id), None)
            if prior is not None:
                if prior != event:
                    raise ValueError("event_id_conflict")
                con.commit()
                return old
            history = replay_source_history((*old, event), synthetic_fixtures_only=True)
            payload = _encode(event)
            digest = _digest(heads.get(event.case_key, (0, ""))[1], payload)
            seq = len(history)
            con.execute(
                "INSERT INTO source_events VALUES (?,?,?,?)", (event.case_key, seq, payload, digest)
            )
            con.execute(
                "INSERT INTO source_heads VALUES (?,?,?) ON CONFLICT(case_key) DO UPDATE SET "
                "seq=excluded.seq,digest=excluded.digest",
                (event.case_key, seq, digest),
            )
            con.commit()
            return history
    except (OSError, sqlite3.Error) as exc:
        raise JournalError("journal_write_unavailable") from exc
