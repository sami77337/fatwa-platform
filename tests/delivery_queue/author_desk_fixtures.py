"""Temporary synthetic journal and ephemeral test-only MUFTI key."""
from base64 import urlsafe_b64encode
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from apps.delivery_planner.trusted_identity import SignedApprovalReceipt, Ed25519ApprovalVerifier, IdentityStatus, approval_signing_payload
from apps.fast9_case_source_join.answer_drafts import AUTHOR, REVIEWER, CASE_KEY
from apps.fast9_case_source_join import source_journal as journal
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.draft_source_review import inspect_draft_source

TITLE = 'عنوان الجواب الاصطناعي'
BODY = '  نصٌّ عربي للاختبار فقط، دون إفتاء.\r\nفقرة ثانية\t محفوظة كما هي.  '


class JournalFixture:
    def __init__(self):
        self.temp = TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.revoked = False
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.verifier = Ed25519ApprovalVerifier(issuer='test-identity', audience='fatwa.return',
            trusted_public_keys={'test-key': public},
            identity_lookup=lambda subject: IdentityStatus('mufti-fixture', 'MUFTI', True),
            is_revoked_or_consumed=lambda *args: self.revoked)

    def close(self):
        self.temp.cleanup()

    def snapshot(self):
        return journal.read_case_review(self.directory, synthetic_fixtures_only=True)

    def files(self):
        return {p.name: p.read_bytes() for p in self.directory.iterdir()}

    def pins(self):
        snapshot = self.snapshot()
        reading = inspect_draft_source(CASE_KEY, 1, snapshot.events, synthetic_fixtures_only=True)
        return dict(reviewer=REVIEWER, count=len(snapshot.events),
            source_digest=journal.history_digest(snapshot.events), draft_digest=reading.draft_revision_sha256)

    def draft(self, body=BODY):
        snapshot = self.snapshot()
        return journal.save_answer_draft(self.directory, author=AUTHOR,
            base_revision=len(snapshot.drafts), count=len(snapshot.events),
            source_digest=journal.history_digest(snapshot.events), reply_digest=snapshot.reply_digest,
            title=TITLE, body=body, evidence_seen=True, synthetic_fixtures_only=True)

    def note(self, action):
        snapshot = self.snapshot()
        draft = snapshot.drafts[-1]
        return journal.record_draft_note(self.directory, reviewer=AUTHOR if action == 'submit' else REVIEWER,
            action=action, text='', revision=draft.revision, draft_digest=draft.digest,
            note_count=len(snapshot.draft_notes), synthetic_fixtures_only=True)

    def ready(self):
        journal.append_source_event(self.directory, sample_source_events(CASE_KEY, 'received')[0], synthetic_fixtures_only=True)
        journal.acknowledge_review(self.directory, **self.pins(), reply_digest=self.snapshot().reply_digest, synthetic_fixtures_only=True)
        self.draft()
        self.note('submit')
        self.note('confirm')

    def correct_source(self):
        journal.append_source_event(self.directory, sample_source_events(CASE_KEY, 'corrected')[-1], synthetic_fixtures_only=True)

    def request_clarification(self):
        return journal.record_clarification(self.directory, **self.pins(),
            thread_digest=self.snapshot().thread_digest, kind='request',
            value='استيضاح اصطناعي', synthetic_fixtures_only=True)

    def signed_response(self, request, **changes):
        evidence = request['evidence']
        now = datetime.now(UTC)
        fields = dict(case_key=evidence['case_key'], answer_revision=evidence['answer_revision'],
            answer_sha256=evidence['answer_sha256'], source_digest=evidence['source_digest'],
            reply_digest=evidence['reply_digest'], approver_id='mufti-fixture', approver_role='MUFTI',
            decision='APPROVE_RETURN_TO_ORIGIN', receipt_id='fixture-receipt',
            issued_at=now.isoformat(), expires_at=(now + timedelta(minutes=4)).isoformat(),
            issuer='test-identity', audience='fatwa.return', key_id='test-key', nonce='N' * 43,
            plan_sha256=request['plan_sha256'], signature_b64url='')
        fields.update(changes)
        receipt = SignedApprovalReceipt(**fields)
        signature = urlsafe_b64encode(self.key.sign(approval_signing_payload(receipt))).decode().rstrip('=')
        receipt = replace(receipt, signature_b64url=signature)
        return json.dumps({'request_sha256': request['request_sha256'], 'receipt': asdict(receipt)}, ensure_ascii=False)
