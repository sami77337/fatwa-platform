"""Transactional local journal for the fixed synthetic case-source history."""

import json
import os
import sqlite3
import stat
import tempfile
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
from itertools import groupby
from pathlib import Path

from apps.editorial_export.services import require_development

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


def _verified(con: sqlite3.Connection) -> tuple[dict, dict]:
    entries = con.execute(
        "SELECT name,sql FROM sqlite_schema LIMIT ?", (len(_SCHEMA) + 1,)
    ).fetchall()
    schema = dict(entries)
    if (
        len(entries) != len(_SCHEMA)
        or schema != _SCHEMA
        or con.execute("PRAGMA application_id").fetchone() != (_APP_ID,)
        or con.execute("PRAGMA user_version").fetchone() != (1,)
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
    return histories, heads


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


def read_source_history(
    directory: Path, case_key: str, *, synthetic_fixtures_only: bool = False
) -> tuple[SourceEvent, ...]:
    """Read a verified committed snapshot; an absent case/file returns an empty tuple."""
    require_development(synthetic_fixtures_only)
    source_receipt(case_key)
    try:
        path = _path(directory)
        if not _exists(path):
            return ()
        with closing(_connect(path, False)) as con:
            histories, _ = _verified(con)
            return histories.get(case_key, ())
    except (OSError, sqlite3.Error) as exc:
        raise JournalError("journal_read_unavailable") from exc


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
            histories, heads = _verified(con)
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
