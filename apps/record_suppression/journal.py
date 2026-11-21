"""Development-only durable metadata floor, kept outside database/media backups.

Appending precedes the SQL insert. A later rollback deliberately leaves a newer
floor: ordinary reads fail closed until an explicitly authorized reconciliation.
This is not a production backup policy, retention engine or purge mechanism.
"""

import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path

from . import catalog
from .catalog import SuppressionDenied


def replace_private_payload(root, raw):
    """Atomically replace already validated private metadata, with file/directory fsync."""
    fd, name = tempfile.mkstemp(prefix="decision-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, root / "decisions.json")
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class LocalJournal:
    def __init__(self, *, root, ledger_id):
        self.root = Path(root)
        self.ledger_id = catalog.uuid_text(ledger_id)

    def _root(self):
        if os.environ.get("FATWA_PRODUCTION") != "0" or not self.root.is_absolute():
            raise SuppressionDenied("suppression_development_journal_required")
        try:
            value = self.root.lstat()
            if (
                not stat.S_ISDIR(value.st_mode)
                or self.root.resolve() != self.root
                or value.st_uid != os.getuid()
                or value.st_mode & 0o077
            ):
                raise ValueError
        except (OSError, ValueError) as exc:
            raise SuppressionDenied("suppression_journal_root_invalid") from exc

    def _open(self, name, flags):
        self._root()
        try:
            fd = os.open(self.root / name, flags | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
            ):
                os.close(fd)
                raise ValueError
            return fd
        except (OSError, ValueError) as exc:
            raise SuppressionDenied("suppression_journal_missing_or_unsafe") from exc

    def snapshot(self):
        fd = self._open("decisions.json", os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise SuppressionDenied("suppression_journal_bound")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise SuppressionDenied("suppression_journal_invalid") from exc
        if (
            type(data) is not dict
            or set(data) != {"format", "ledger_id", "events"}
            or data["format"] != "fatwa.suppression.v1"
            or data["ledger_id"] != self.ledger_id
            or raw != catalog.canonical(data).encode()
        ):
            raise SuppressionDenied("suppression_journal_invalid")
        catalog.events(data["events"], self.ledger_id)
        return data["events"]

    def _write(self, values):
        raw = catalog.canonical(
            {"format": "fatwa.suppression.v1", "ledger_id": self.ledger_id, "events": values}
        ).encode()
        replace_private_payload(self.root, raw)

    def initialize(self):
        """Explicit bootstrap of a fresh synthetic journal; never repair/overwrite."""
        self._root()
        fd = self._open("lock", os.O_RDWR | os.O_CREAT)
        with os.fdopen(fd, "rb+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (self.root / "decisions.json").exists():
                raise SuppressionDenied("suppression_journal_already_initialized")
            self._write([])

    def append(self, expected, value):
        fd = self._open("lock", os.O_RDWR)
        with os.fdopen(fd, "rb+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.snapshot()
            if current != expected:
                raise SuppressionDenied("suppression_journal_stale")
            catalog.events([*current, value], self.ledger_id)
            self._write([*current, value])
            return [*current, value]
