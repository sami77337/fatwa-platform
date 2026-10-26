# Synthetic revision lineage consistency inspector

Read-only FAST7C development component based on FAST6 PR #121 at
`667fd70217d794169c23569ce2df0396dcd27f7c`. Only new files under
`apps/revision_lineage_inspector/`, `tools/revision_lineage_inspector/`, and
`tests/revision_lineage_inspector/` are owned by this change.

Existing services expose immutable revision summaries and workflow audit windows.
This inspector adds consistency observations across supplied evidence without
fetching records, changing a snapshot, or reconstructing missing relationships.
It reuses `build_revision_audit`, `build_audit_provenance`, the synthetic payload
parser and exact byte slices, prepared-intake validation, and workflow transition
contracts. It never calls a transition service, database, network, or resolver.

## Run

From the repository root with the existing Python 3.13 dependencies:

```text
python -B -m tools.revision_lineage_inspector --synthetic-fixtures-only
python -B -m tools.revision_lineage_inspector --synthetic-fixtures-only --scenario source-mismatch
```

The CLI accepts only built-in invented fixtures. There is no file/stdin input or
output-file option. JSON is emitted to stdout. Scenarios: `consistent`,
`revision-order`, `case-mismatch`, `source-mismatch`, `event-order`,
`reference-mismatch`, `missing-workflow`. Exit 0 means no detected inconsistency
in the available evidence, 1 means an inconsistent observation, and 2 means an
invalid invocation or unsupported input shape. Missing evidence remains visible
even on exit 0; it is not an acceptance pass.

Fixture identity: `revision-lineage.synthetic.v1`. Fixed original payload SHA256:
`b1b847aed7e44a5fb494cf2ce8cdcdb3828e8b4cbd46b025c3474773dfa2766c`.
All scenarios derive from this same source payload and vary only supplied DTOs.
It contains invented Arabic technical text, not scholarly answers or private data.

## Python interface

```python
from apps.revision_lineage_inspector import inspect_lineage, serialize_report

report = inspect_lineage(
    record,
    expected_case_id="SYN-LINEAGE-001",
    workflow=worklist,
    expected_row_id=row_uuid,
    expected_batch_id=batch_uuid,
    source_payload=original_synthetic_bytes,
    synthetic_fixtures_only=True,
)
payload = serialize_report(report)
```

The supplied immutable `DraftRecord` is required. Workflow evidence, original
payload, and the row/batch UUID pair are optional. The literal-True guard is an
integration declaration, not a sensitive-data detector. Use synthetic fixtures
only. Unsupported mutable types, malformed scalar shapes, and exceeded bounds
raise `LineageInputError` with static codes. Bounded contract inconsistencies,
including duplicate revision/event identities or invalid source JSON, produce
`FAIL` checks so consumers can inspect the discrepancy.

## Result semantics and limits

Schema `fatwa.revision-lineage-inspector.v1` reports ordered checks with
`PASS`, `FAIL`, or `UNAVAILABLE`. Any `FAIL` produces `INCONSISTENT`; otherwise
the status is `CONSISTENT_WITH_LIMITATIONS`. The output includes counts and
supplied revision numbers, without source text, editor labels, case IDs or URLs.
Serialization is deterministic, compact and bounded to 64 KiB. Input ceilings
are 100 snapshots, 100 events per row, 100 references per snapshot/row, 50 page
rows, 101 batches, 10,000 characters per snapshot text field, and 1,000,000 bytes
for an original source payload. Existing contract limits also apply.

- Revision numbers must increase in supplied order. Gaps do not invent missing
  snapshots or events. The original record and sequence remain unchanged.
- Case strings compare exactly; workflow selection uses explicit row and batch
  UUIDs. Matching labels and UUID pins do not prove a draft-to-workflow mapping.
- Original row and reference attribution uses exact UTF-8 byte offsets, source
  text and ordinal, not character positions or normalized text. Source field and
  intake comparisons remain exact. Caller-supplied bytes have no authoritative
  batch digest in the read DTO, so payload-to-batch binding stays unavailable.
- Events are checked in the reader's newest-first UTC/UUID order. UUID tie breaks
  provide presentation order only: equal timestamps make causal chain order
  unavailable, and tied latest events make the latest-state relationship
  unavailable. Known action/state pairs use existing pure contracts and confer
  no permission or scholarly approval.
- Reference shape, byte spans, unique identities and current status consistency
  are checked where available. Full six-field snapshot pointers retain their
  source identity. A pointer absent from initial intake may be a later addition;
  its source membership is unavailable, not automatically corrupt.
- `PASS` for pointer structure or membership does not verify a book, citation or
  source authenticity. `VERIFIED` on a workflow DTO supplies neither historical
  reference state nor a link to a snapshot.
- Event-to-snapshot links, authenticated editor attribution, full history and
  historical workflow references are always unavailable under current DTOs.
  Audit events are never treated as text snapshots. No timestamp is invented.

## Verification

```text
python -B -m unittest discover -s tests/revision_lineage_inspector -v
python -B manage.py test tests/revision_lineage_inspector tests/revision_core tests.fatwa_drafts.test_revision_audit tests.fatwa_drafts.test_provenance_summary tests.fatwa_drafts.test_domain tests.editorial_demo.test_audit_provenance_projection tests.editorial_demo.test_audit_export_contract tests.editorial_demo.test_audit_adversarial --settings=config.settings.test --noinput -v 1
python -m ruff check apps/revision_lineage_inspector tests/revision_lineage_inspector tools/revision_lineage_inspector --no-force-exclude
python -m ruff format --check apps/revision_lineage_inspector tests/revision_lineage_inspector tools/revision_lineage_inspector --no-force-exclude
```

Tests use invented DTOs, fixed timestamps/UUIDs, Arabic and CRLF source bytes,
negative mutations, and executable CLI subprocesses. No PostgreSQL acceptance
or owner ZIP validation is claimed. No migration or integration registration is
needed; rollback removes these additive modules. Existing FAST7/FAST7B modules,
configuration, approval settings and shared source files remain unchanged.

Local verification on 2026-10-26: **136/136 tests passed** (33 new, 103 directly
affected existing tests), Django system check clean, Ruff lint/format clean.
One independent focused review found two P2 issues: timestamp ties incorrectly
implied causal sequence, and an empty source span was accepted without raw
payload. Both were corrected and covered by regression tests in the final run.
An initial test invocation using namespace-package labels failed discovery;
the path-based command above resolved it without configuration changes. Early
test expectations were corrected to distinguish semantic FAIL reports from
shape exceptions. These are synthetic unit/contract/CLI results, not database
or source-owner acceptance. The final review agent independently ran 32 tests;
the coordinator added and passed the final empty-span regression afterward.

**NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.
U03/U10 remain pending. No grants, scholarly approvals, publication or deployment.**
