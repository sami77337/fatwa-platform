# Proposed root/E5 DB integration (not an implemented DB test module)

E3 owns pure reference tests only. Per root clarification, this lane creates no
`tests/reference_links_db/test_wave7_*.py` or other permanent DB test file. Proposed
root/E5-owned module: `tests/wave7_foundation/test_reference_service.py`, label
`tests.wave7_foundation.test_reference_service`, selected only in the existing
guarded Wave7 PG17/18 jobs after assembling the actual E3 service file.

Use `TransactionTestCase`, not `TestCase`; seed outside another transaction and
let `verify_batch_references` enter its own guard. The current approved
`Wave7TestRunner` supplies/claims the fresh test DB. No keepdb/shared-owner target,
port-1 discovery, optional import or zero-case fallback is appropriate.

Concrete starter module for E5 to apply/review in its ownership:

```python
from uuid import uuid4
from unittest.mock import patch
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
from apps.intake_workflow.references import verify_batch_references

class ReferenceServiceDatabaseTests(TransactionTestCase):
    def setUp(self):
        g.require_synthetic_write(synthetic_fixtures_only=True)
        f.seed_reference_catalog(synthetic_fixtures_only=True)

    def persist(self):
        raw = f.synthetic_payload()
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = IntakeBatch.objects.create(idempotency_key=uuid4().hex,
                original_payload=raw, payload_sha256=parsed.payload_sha256)
            for n, (row, source, refs) in enumerate(zip(parsed.items,
                    parsed.item_sources, parsed.reference_sources, strict=True), 1):
                item = IntakeItem.objects.create(batch=batch, row_ordinal=n,
                    external_id=c.valid_external_id(row.get('external_id')) if isinstance(row, dict) else None,
                    question_original=row.get('question') if isinstance(row, dict)
                        and isinstance(row.get('question'), str) else None,
                    original_row=source.text, source_byte_start=source.start,
                    source_byte_end=source.end, intake_status='BLOCKED_INVALID')
                for ordinal, pointer in enumerate(refs, 1):
                    IntakeReference.objects.create(intake_item=item, reference_ordinal=ordinal,
                        original_pointer=pointer.text, source_byte_start=pointer.start,
                        source_byte_end=pointer.end)
        return batch

    def test_current_catalog_and_sources_with_stable_replay(self):
        batch = self.persist()
        originals = list(IntakeItem.objects.filter(batch=batch).values())
        first = verify_batch_references(batch.pk, synthetic_fixtures_only=True)
        self.assertEqual(len(first.items), 8)
        self.assertEqual(originals, list(IntakeItem.objects.filter(batch=batch).values()))
        self.assertEqual(IntakeReference.objects.filter(
            intake_item__batch=batch, reference_status='VERIFIED').count(), 3)
        self.assertEqual(ReviewEvent.objects.count(), 0)
        with CaptureQueriesContext(connection) as queries:
            second = verify_batch_references(batch.pk, synthetic_fixtures_only=True)
        self.assertEqual(first, second)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith('UPDATE') for q in queries))

    def test_partial_derived_update_is_rolled_back(self):
        batch = self.persist()
        before = list(IntakeReference.objects.filter(intake_item__batch=batch).values())
        original = QuerySet.bulk_update
        def fail_after_first(queryset, objects, fields, **kwargs):
            original(queryset, objects[:1], fields, **kwargs)
            raise RuntimeError('synthetic partial write')
        with patch.object(QuerySet, 'bulk_update', fail_after_first):
            with self.assertRaisesRegex(RuntimeError, 'synthetic partial write'):
                verify_batch_references(batch.pk, synthetic_fixtures_only=True)
        self.assertEqual(before, list(IntakeReference.objects.filter(intake_item__batch=batch).values()))
```

This proposal has not been installed/collected as a permanent test module. Equivalent
scenarios executed against the real owned synthetic PG17/18 databases; recorded
counts refer to those temporary probes, not this proposed class.

Extend this module with the already observed scenarios: source tokens containing
73.000000000000001, 1e-20000, an extreme fallback Decimal exponent and a 6000-digit
integer; malformed/null pointers; mismatched C2 fields; incomplete persisted
ordinals; actual read failure; disabled guard/outer transaction. The fixed fixtures
need no new E1 dependency for these tests. A separate negative-catalog test must
insert before normal seed: fixed edition7001, allowed child row2 pointing to row99
whose title equals root row1. It must be MISMATCHED with no identity/citation.
Create this negative fixture only in the freshly isolated test case's guarded seed unit,
never mutate/disable the immutable source triggers or repair a seeded catalog.

No shared patch is needed for E3's service itself. E1 must persist every SourceSlice
and invoke E3 after committing intake; E4 must not call this write service from GET.
The root/E5 test/CI assignment and final combined acceptance remain separate.
