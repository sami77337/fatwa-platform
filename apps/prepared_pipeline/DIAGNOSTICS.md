# Offline synthetic batch diagnostics and reconciliation

This additive workflow uses the existing FAST2 `prepare_batches` service and C1
CSV/JSON/JSONL adapters. Existing preparation reports, APIs and C1 exports are
unchanged. No HTTP routes, database operations or mapping configuration are added.
Existing GET/HEAD and loopback guards remain unchanged.

## Try the committed synthetic fixtures

Run from the repository root in PowerShell (Python 3.13, standard library only):

```powershell
$demo = @('--synthetic-fixtures-only',
  '--batch', 'a', 'tools/content_intake/examples/synthetic-batch-a.csv',
  '--batch', 'b', 'tools/content_intake/examples/synthetic-batch-b.jsonl',
  '--expect-batch', 'a', '--expect-batch', 'b',
  '--source-id', 'synthetic-source-a')
python -m tools.content_intake diagnose @demo --preview
python -m tools.content_intake diagnose @demo --show-row a 2
python -m tools.content_intake diagnose @demo --export-bundle tests/content_intake/synthetic-diagnostic-bundle
python -m tools.content_intake diagnose @demo --check-bundle tests/content_intake/synthetic-diagnostic-bundle
```

The fixture intentionally returns exit **1**: four original rows, three blocked,
one process-local receipt, one cross-batch duplicate group and one missing source
pointer. `--show-row BATCH ROW` shows the selected original row's diagnostics and
duplicate locations. `--preview` lists all rows with Arabic recovery instructions.
With neither flag the command emits canonical JSON. A blocked row, malformed file,
missing expected batch or command error returns 1; review-only results return 0.
Exports are allowed even for blocked input, so a human can reconcile all findings.

Use `--expect-batch ID` to report absent batch identities. Each repeated `--batch`
requires a unique bounded ID. A missing or unreadable local path fails the command
with a fixed error and creates no bundle. Malformed readable files are isolated,
retain their complete bytes/SHA, and allow independent files to be diagnosed.

`--source-id ID` supplies an explicit inventory of available source identities.
It establishes presence only, never a trusted mapping, citation, or scholarly
approval. Omitting the inventory reports `source_inventory_not_supplied`;
`--empty-source-inventory` explicitly declares that no source is available.
Source identities are compared exactly without Arabic normalization, trimming or
mapping inference. Valid pointers in blocked rows are still checked independently.

## Python and report contract

```python
from apps.prepared_pipeline.batches import PreparedInput
from apps.prepared_pipeline.diagnostics import diagnose_batches

result = diagnose_batches(
    [PreparedInput('a', synthetic_bytes, '.json')],
    synthetic_fixtures_only=True,
    available_source_ids=['synthetic-source-a'],
    expected_batch_ids=['a', 'b'],
)
report = result.report
```

Every row includes the **original serialized preparation row**, independent
diagnostics with `field`, `code`, severity and `recovery_ar`, and a byte receipt.
Original statuses, findings, reference results and draft eligibility are retained;
source-presence diagnostics do not silently alter them. `summary.status_counts`,
`finding_counts`, `reference_counts`, `draft_count` and `record_count` reconcile
with `rows[*].preparation`. `diagnostic_counts` separately counts every diagnostic
occurrence; it can exceed the row count. Missing batches and malformed files have
separate collection/file counts and are never fabricated into parsed rows.

`row_id = input_sha256:byte_start:byte_end` is stable for fixed original bytes,
even when batch order changes. `(batch_id, row_id)` distinguishes identical files
supplied under different identities. Byte offsets are zero-based with an exclusive
end. CSV and JSONL spans include physical terminators; JSON spans cover complete
array values without separators. BOM, headers, skipped blank lines and malformed
files remain recoverable from `inputs[*].raw_base64`. Each row additionally retains
its exact byte slice in `provenance.raw_base64`. Original text is never corrected.

Duplicate groups hold each occurrence once and rows reference a stable group ID;
they avoid repeating every duplicate location on every row. All occurrences,
including originally invalid rows, remain blocked by the existing orchestrator.

## Deterministic reconciliation bundle

The new output directory contains `diagnostics.json`, `rows.jsonl`, `recovery.txt`
and `manifest.json`. The manifest pins the byte length and SHA-256 of the other
three files. Fixed input bytes, argument order and explicit inventories produce
identical outputs. Reports keep immutable canonical bytes; `.report` returns a
detached object. `--check-bundle` compares every expected artifact using bounded
reads. Export never overwrites an existing directory or source. An I/O failure
during writing may leave an incomplete new directory; check it before using it.

Existing aggregate limits remain 1,000,000 input bytes, 1,000 parsed records,
1,000 files and 100 reference pointers per row. Each inventory/expectation list
is bounded at 1,000 unique IDs of at most 100 characters. A diagnostic report and
the combined export bundle are each capped at 32,000,000 bytes; exceeding a limit
fails without creating a bundle. No timestamps, absolute local paths, credentials
or inferred mappings are added to exports. The synthetic acknowledgement is an
explicit caller assertion, not a private-data detector.

All recovery steps are manual: retain the original, edit a separate synthetic
copy, rerun the command, and verify a new bundle. No source file is written.
No migrations, real/private data, publication or scholarly approval actions.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED.
