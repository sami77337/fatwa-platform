import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest import TestCase
from unittest.mock import patch

from apps.fast9_case_source_join import source_journal as journal
from apps.fast9_case_source_join.source_history import CORRECTION_BODIES, source_receipt


class SourceJournalTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.db = self.directory / journal.JOURNAL_FILENAME
        self.root = source_receipt("intake-7")
        self.edit = replace(
            self.root,
            event_id="edit",
            kind="corrected",
            prior_event_id=self.root.event_id,
            body_utf8=CORRECTION_BODIES[0],
        )
        self.removal = replace(
            self.edit, event_id="removed", kind="deleted", prior_event_id="edit", body_utf8=None
        )

    def put(self, event):
        return journal.append_source_event(self.directory, event, synthetic_fixtures_only=True)

    def read(self, key="intake-7"):
        return journal.read_source_history(self.directory, key, synthetic_fixtures_only=True)

    def test_read_missing_without_creating_and_reject_invalid_first_write(self):
        self.assertEqual(self.read(), ())
        with self.assertRaises(ValueError):
            self.put(self.edit)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_roundtrip_case_isolation_idempotency_and_post_deletion(self):
        for event in (self.root, self.edit, self.removal):
            self.put(event)
        other = source_receipt("intake-1")
        self.put(other)
        other_edit = replace(
            other,
            event_id=self.edit.event_id,
            kind="corrected",
            prior_event_id=other.event_id,
            body_utf8=CORRECTION_BODIES[1],
        )
        self.put(other_edit)
        self.assertEqual(self.read(other.case_key), (other, other_edit))
        self.assertEqual(self.read("intake-4"), ())
        before = self.db.read_bytes()
        expected = (self.root, self.edit, self.removal)
        self.assertEqual(self.read(), expected)
        self.assertEqual(self.put(self.edit), expected)
        with self.assertRaisesRegex(ValueError, "event_id_conflict"):
            self.put(replace(self.edit, body_utf8=CORRECTION_BODIES[1]))
        with self.assertRaisesRegex(ValueError, "invalid_predecessor"):
            self.put(replace(self.edit, event_id="late", prior_event_id=self.removal.event_id))
        self.assertEqual(self.db.read_bytes(), before)

    def test_checkpoint_matches_stored_tip_and_previous_prefix(self):
        self.assertIsNone(journal.history_digest(()))
        root_tip = journal.history_digest(self.put(self.root))
        self.put(self.edit)
        history = self.read()
        with closing(sqlite3.connect(self.db)) as con, con:
            (stored_tip,) = con.execute("SELECT digest FROM source_heads").fetchone()
        self.assertEqual(journal.history_digest(history), stored_tip)
        self.assertEqual(journal.history_digest(history[:1]), root_tip)
        self.assertNotEqual(root_tip, stored_tip)

    def test_competing_writers_cannot_both_extend_the_same_tip(self):
        self.put(self.root)
        begin = Barrier(2)

        def compete(event):
            begin.wait(timeout=5)
            try:
                self.put(event)
                return event
            except ValueError as e:
                self.assertEqual(str(e), "invalid_predecessor")
                return None

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(compete, [self.edit, replace(self.edit, event_id="other")]))
        (winner,) = [e for e in results if e]
        self.assertEqual(self.read(), (self.root, winner))

    def reviewed_version(self):
        events, _ = journal.read_review_state(self.directory, synthetic_fixtures_only=True)
        observation = journal.inspect_draft_source(
            "intake-7", 1, events, synthetic_fixtures_only=True
        )
        return {
            "reviewer": "synthetic-reviewer",
            "count": len(events),
            "source_digest": journal.history_digest(events),
            "draft_digest": observation.draft_revision_sha256,
            "synthetic_fixtures_only": True,
        }

    def test_review_requires_exact_draft_and_source_then_replays_without_writing(self):
        self.put(self.root)
        version = self.reviewed_version()
        before = self.db.read_bytes()
        for values, error in (
            ({"reviewer": "other-reviewer"}, ValueError),
            ({"draft_digest": "0" * 64}, journal.ReviewConflict),
            ({"source_digest": "0" * 64}, journal.ReviewConflict),
        ):
            with self.assertRaises(error):
                journal.acknowledge_review(self.directory, **(version | values))
        self.assertEqual(self.db.read_bytes(), before)
        receipt = journal.acknowledge_review(self.directory, **version)
        self.assertEqual(
            journal.read_review_state(self.directory, synthetic_fixtures_only=True),
            ((self.root,), receipt),
        )
        persisted = self.db.read_bytes()
        self.assertEqual(journal.acknowledge_review(self.directory, **version), receipt)
        self.assertEqual(self.db.read_bytes(), persisted)
        self.put(self.edit)
        events, prior = journal.read_review_state(self.directory, synthetic_fixtures_only=True)
        self.assertEqual((events, prior), ((self.root, self.edit), receipt))
        self.assertNotEqual(prior.source_digest, journal.history_digest(events))
        renewed = journal.acknowledge_review(self.directory, **self.reviewed_version())
        self.assertEqual(renewed.count, 2)
        self.assertEqual(
            journal.read_review_state(self.directory, synthetic_fixtures_only=True)[1], renewed
        )

    def test_review_waiting_on_a_correction_cannot_record_the_old_view(self):
        self.put(self.root)
        version = self.reviewed_version()
        locked = Event()
        trying_review = Event()
        connect = journal._connect

        def pause_writer(path, writable):
            con = connect(path, writable)
            locked.set()
            if not trying_review.wait(5):
                con.close()
                raise AssertionError("review did not attempt entry")
            return con

        with ThreadPoolExecutor(max_workers=2) as pool:
            with patch.object(journal, "_connect", pause_writer):
                writer = pool.submit(self.put, self.edit)
                self.assertTrue(locked.wait(5))

            def review_connect(path, writable):
                trying_review.set()
                return connect(path, writable)

            with patch.object(journal, "_connect", review_connect):
                reviewer = pool.submit(journal.acknowledge_review, self.directory, **version)
                self.assertEqual(writer.result(timeout=6), (self.root, self.edit))
                with self.assertRaises(journal.ReviewConflict):
                    reviewer.result(timeout=6)
        self.assertEqual(
            journal.read_review_state(self.directory, synthetic_fixtures_only=True),
            ((self.root, self.edit), None),
        )

    def test_reader_preserves_existing_same_process_writer_reservation(self):
        self.put(self.root)
        contender = """
import sqlite3, sys
from contextlib import closing
with closing(sqlite3.connect(sys.argv[1], timeout=0)) as con:
    try:
        con.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY:
            raise
        sys.exit(23)
    sys.exit(0)
"""

        def contend():
            return subprocess.run(
                [sys.executable, "-B", "-c", contender, str(self.db)], check=False, timeout=10
            ).returncode

        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            self.assertEqual(contend(), 23)
            self.assertEqual(self.read(), (self.root,))
            self.assertEqual(contend(), 23)
        self.assertEqual(contend(), 0)

    def test_wal_format_without_sidecars_stays_untouched(self):
        def snapshot():
            return self.db.read_bytes(), self.db.stat().st_mtime_ns

        self.put(self.root)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
        self.assertEqual(list(self.directory.iterdir()), [self.db])
        before = snapshot()
        for call in (self.read, lambda: self.put(self.edit)):
            with self.assertRaises(journal.JournalError):
                call()
            self.assertEqual(snapshot(), before)
            self.assertEqual(list(self.directory.iterdir()), [self.db])

    def test_unrelated_database_and_non_database_are_unchanged(self):
        self.db.write_bytes(b"not a journal")
        for i in range(2):
            before = self.db.read_bytes()
            for operation in (lambda: self.put(self.root), self.read):
                with self.assertRaises(journal.JournalError):
                    operation()
            self.assertEqual(self.db.read_bytes(), before)
            if i == 0:
                self.db.unlink()
                with closing(sqlite3.connect(self.db)) as con, con:
                    con.execute("CREATE TABLE separate (some_value TEXT)")

    def test_mutation_rejected_and_mismatched_tail_detected_before_append(self):
        self.put(self.root)
        with closing(sqlite3.connect(self.db)) as con, con:
            for sql in (
                "DELETE FROM source_events",
                "UPDATE source_events SET seq=2",
                "INSERT OR REPLACE INTO source_events SELECT * FROM source_events",
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute(sql)
            con.execute("UPDATE source_heads SET seq=2")
        before = self.db.read_bytes()
        for action in (self.read, lambda: self.put(self.edit)):
            with self.assertRaises(journal.JournalError):
                action()
        self.assertEqual(self.db.read_bytes(), before)

    def test_case_capacity_allows_exact_retry_but_rejects_additional_event(self):
        tip = self.root
        self.put(tip)
        for n in range(127):
            next_event = replace(self.edit, event_id=f"change-{n}", prior_event_id=tip.event_id)
            self.put(next_event)
            tip = next_event
        expected = self.read()
        self.assertEqual(len(expected), 128)
        self.assertEqual(self.put(tip), expected)
        with self.assertRaises(ValueError):
            self.put(replace(tip, body_utf8=bytearray(tip.body_utf8)))
        with self.assertRaises(ValueError):
            self.put(replace(tip, event_id="extra", prior_event_id=tip.event_id))
        self.assertEqual(self.read(), expected)

    def test_unexpected_sidecar_rejected_without_creation(self):
        wal = self.db.with_name(self.db.name + "-wal")
        wal.write_bytes(b"unrelated")
        for action in (self.read, lambda: self.put(self.root)):
            with self.assertRaises(journal.JournalError):
                action()
        self.assertFalse(self.db.exists())
        self.assertEqual(wal.read_bytes(), b"unrelated")

    def test_guards_before_io(self):
        with self.assertRaises(ValueError):
            journal.append_source_event(self.directory, self.root)
        for opts in (
            {"FATWA_PRODUCTION": "1"},
            {"DJANGO_SETTINGS_MODULE": "config.settings.production"},
        ):
            with patch.dict(os.environ, opts), self.assertRaises(ValueError):
                self.put(self.root)
        with self.assertRaisesRegex(ValueError, "invalid_event"):
            self.put(replace(self.root, case_key=[]))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_process_exit_before_commit_restores_previous_tip(self):
        self.put(self.root)
        script = """
import os, sqlite3, sys
from pathlib import Path
from dataclasses import replace
from apps.fast9_case_source_join import source_journal as j
from apps.fast9_case_source_join.source_history import source_receipt, CORRECTION_BODIES
root=source_receipt("intake-7")
event=replace(root, kind="corrected", prior_event_id=root.event_id, event_id="edit", body_utf8=CORRECTION_BODIES[0])
connect=sqlite3.connect
def crashing_connect(*a, **kw):
    conn=connect(*a, **kw)
    conn.set_trace_callback(lambda sql: os._exit(31) if sql.strip().upper()=="COMMIT" else None)
    return conn
sqlite3.connect=crashing_connect
j.append_source_event(Path(sys.argv[1]),event,synthetic_fixtures_only=True)
"""
        process = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.directory)], timeout=15
        )
        self.assertEqual(process.returncode, 31)
        self.assertEqual(self.read(), (self.root,))
        self.assertEqual(self.put(self.edit), (self.root, self.edit))
