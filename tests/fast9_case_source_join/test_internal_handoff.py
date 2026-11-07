"""An author submits a particular draft; reviewer only checks that version."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from apps.fast9_case_source_join.answer_drafts import AUTHOR, REVIEWER, DraftInputError
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import (
    ReviewConflict, append_source_event, history_digest, read_case_review,
    record_draft_note, save_answer_draft,
)


class InternalHandoffTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        received, self.correction = sample_source_events("intake-7", "corrected")
        self.events = append_source_event(self.directory, received, synthetic_fixtures_only=True)

    def draft(self, base, body):
        return save_answer_draft(
            self.directory, author=AUTHOR, base_revision=base,
            count=len(self.events), source_digest=history_digest(self.events),
            reply_digest="", title="عنوان تدريبي", body=body,
            evidence_seen=True, synthetic_fixtures_only=True,
        )

    def act(self, action, draft, count, *, actor=None, text=""):
        return record_draft_note(
            self.directory,
            reviewer=actor or (AUTHOR if action == "submit" else REVIEWER),
            revision=draft.revision, draft_digest=draft.digest, note_count=count,
            action=action, text=text, synthetic_fixtures_only=True,
        )

    def test_internal_confirmation_does_not_approve_publication(self):
        version1 = self.draft(0, "مسودة داخلية أولى")
        sent = self.act("submit", version1, 0)
        self.assertEqual(self.act("submit", version1, 0), sent)
        with self.assertRaises(DraftInputError):
            self.act("confirm", version1, 1, actor=AUTHOR)
        checked = self.act("confirm", version1, 1)
        self.assertEqual([sent.action, checked.action], ["submit", "confirm"])
        review = read_case_review(self.directory, synthetic_fixtures_only=True)
        self.assertEqual([e.actor for e in review.draft_notes], [AUTHOR, REVIEWER])
        self.assertEqual(len(review.drafts), 1)
        with self.assertRaises(ReviewConflict):
            self.act("confirm", version1, 2)
        self.events = append_source_event(
            self.directory, self.correction, synthetic_fixtures_only=True
        )
        with self.assertRaises(ReviewConflict):
            self.act("submit", version1, 2)
        version2 = self.draft(1, "بعد تصحيح السؤال")
        self.act("submit", version2, 2)
        self.assertEqual(
            [e.action for e in read_case_review(self.directory, synthetic_fixtures_only=True).draft_notes],
            ["submit", "confirm", "submit"],
        )

    def test_requested_changes_require_a_new_draft_and_explicit_handoff(self):
        first = self.draft(0, "المسودة الأولى")
        self.act("submit", first, 0)
        self.act("request", first, 1, text="يرجى مراجعة التفصيل")
        with self.assertRaises(ReviewConflict):
            self.act("submit", first, 2)
        second = self.draft(1, "المسودة المعدلة")
        self.act("close", second, 2)
        self.act("submit", second, 3)
        self.act("confirm", second, 4)
        self.assertEqual(
            [e.action for e in read_case_review(self.directory, synthetic_fixtures_only=True).draft_notes],
            ["submit", "request", "close", "submit", "confirm"],
        )


if __name__ == "__main__":
    unittest.main()
