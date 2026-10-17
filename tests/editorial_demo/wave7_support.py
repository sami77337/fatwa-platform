"""Owned synthetic E2 database fixtures; no E1 service or source archive dependency."""
from hashlib import sha256
from uuid import uuid4
from django.conf import settings
from django.test import TransactionTestCase
from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference


class OwnedReviewTestCase(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context = g.require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != settings.WAVE7_TEST_DATABASE_NAME:
            raise RuntimeError('E2 tests require their runner-owned disposable test database')

    def create_batch(self, raw=None):
        raw = f.synthetic_payload() if raw is None else raw
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = IntakeBatch.objects.create(idempotency_key=uuid4().hex,
                original_payload=raw, payload_sha256=sha256(raw).hexdigest())
            rows = []
            for ordinal, (value, source) in enumerate(zip(parsed.items, parsed.item_sources, strict=True), 1):
                obj = value if isinstance(value, dict) else {}
                item = IntakeItem.objects.create(batch=batch, row_ordinal=ordinal,
                    external_id=c.valid_external_id(obj.get('external_id')),
                    question_original=obj.get('question') if isinstance(obj.get('question'), str) else None,
                    original_row=source.text, source_byte_start=source.start, source_byte_end=source.end,
                    intake_status='READY_FOR_EDITOR' if ordinal == 7 else 'BLOCKED_INVALID')
                for ref_ordinal, pointer in enumerate(parsed.reference_sources[ordinal-1], 1):
                    IntakeReference.objects.create(intake_item=item, reference_ordinal=ref_ordinal,
                        original_pointer=pointer.text, source_byte_start=pointer.start, source_byte_end=pointer.end)
                rows.append(item)
        return batch, rows
