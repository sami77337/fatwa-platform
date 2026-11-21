"""A separately retained development floor for cleared derivative identities.

The existing suppression journal's filesystem ownership and no-link checks are
reused unchanged. This format has its own closed validator and no source text.
"""

import fcntl
import json
import os

from apps.record_suppression.journal import LocalJournal, replace_private_payload

from . import catalog
from .catalog import DerivedDenied

MAX_BYTES = 8 * 1024 * 1024


class DerivedJournal(LocalJournal):
    def snapshot(self):
        fd = self._open("decisions.json", os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise DerivedDenied("derived_journal_bound")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise DerivedDenied("derived_journal_invalid") from exc
        if (
            type(value) is not dict
            or set(value) != {"format", "ledger_id", "events"}
            or value["format"] != "fatwa.derivative-clearances.v1"
            or value["ledger_id"] != self.ledger_id
            or raw != catalog.canonical(value).encode()
        ):
            raise DerivedDenied("derived_journal_invalid")
        catalog.events(value["events"], self.ledger_id)
        return value["events"]

    def _write(self, values):
        raw = catalog.canonical(
            {
                "format": "fatwa.derivative-clearances.v1",
                "ledger_id": self.ledger_id,
                "events": values,
            }
        ).encode()
        if len(raw) > MAX_BYTES:
            raise DerivedDenied("derived_journal_bound")
        replace_private_payload(self.root, raw)

    def append(self, expected, value):
        fd = self._open("lock", os.O_RDWR)
        with os.fdopen(fd, "rb+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.snapshot()
            if current != expected:
                raise DerivedDenied("derived_journal_stale")
            catalog.events([*current, value], self.ledger_id)
            self._write([*current, value])
            return [*current, value]
