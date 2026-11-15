"""The external human reviewer must receive the question and clarification text."""
from unittest.mock import patch
from django.test import TransactionTestCase
from apps.fast9_case_source_join import source_journal as journal
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from apps.delivery_queue import author_handoff as handoff
from tests.delivery_queue.author_desk_fixtures import JournalFixture


class ApprovalPacketContextTests(TransactionTestCase):
    def setUp(self):
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()

    def request(self):
        return handoff.build_approval_request(self.fixture.directory, case_key=CASE_KEY,
            max_chars=32, split=True, synthetic_fixtures_only=True)

    def test_packet_contains_exact_current_question_not_only_its_hash(self):
        request = self.request()
        self.assertIn('question', request)
        snapshot = self.fixture.snapshot()
        self.assertEqual(request['question']['exact_text'], snapshot.events[-1].body_utf8.decode('utf-8'))
        self.assertEqual(request['question']['source_digest'], request['evidence']['source_digest'])

    def test_completed_clarification_dialogue_is_readable_without_reply_credentials(self):
        self.fixture.request_clarification()
        snapshot = self.fixture.snapshot()
        code = journal.issue_reply_code(self.fixture.directory, **self.fixture.pins(),
            thread_digest=snapshot.thread_digest, grant_revision=snapshot.grant_revision,
            synthetic_fixtures_only=True).code
        text = '  جواب استيضاح اصطناعي\r\nدون تغيير  '
        journal.submit_requester_reply(self.fixture.directory, code, text, synthetic_fixtures_only=True)
        journal.acknowledge_review(self.fixture.directory, **self.fixture.pins(),
            reply_digest=self.fixture.snapshot().reply_digest, synthetic_fixtures_only=True)
        self.fixture.draft()
        self.fixture.note('submit')
        self.fixture.note('confirm')
        request = self.request()
        self.assertIn('clarifications', request)
        self.assertEqual([row['kind'] for row in request['clarifications']], ['request', 'reply'])
        self.assertEqual(request['clarifications'][-1]['exact_text'], text)
        self.assertNotIn(code, str(request))

    def test_source_change_between_candidate_and_context_reads_is_rejected(self):
        original = handoff.read_return_candidate
        def race(*args, **kwargs):
            result = original(*args, **kwargs)
            self.fixture.correct_source()
            return result
        with patch.object(handoff, 'read_return_candidate', side_effect=race), self.assertRaises(ValueError):
            self.request()
