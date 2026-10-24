# Offline synthetic prepared-input processing

For per-row byte receipts, Arabic recovery, explicit source inventory checks and
deterministic reconciliation bundles, see [the offline diagnostic workflow](DIAGNOSTICS.md).

This development-only flow validates caller-supplied **synthetic** editorial input
and creates process-local `received` draft objects with empty answers. It never
persists drafts, fetches media, approves rulings or publishes anything.

## Run

```powershell
# Existing inline synthetic example, Arabic preview or deterministic JSON
python -m apps.prepared_pipeline
python -m apps.prepared_pipeline --json

# Caller-supplied synthetic files; deterministic collection JSON goes to stdout
python -m apps.prepared_pipeline --synthetic-fixtures-only batch-a.csv batch-b.jsonl batch-c.json
```

File mode always emits JSON. Exit code 1 means a file failed to read/parse, a row
was blocked, or a collection limit was exceeded. Review-only input returns 0.
File entries have stable positional IDs (`input-0001`, etc.) in argument order;
the exact raw SHA-256 identifies readable input, including BOM/newlines. Unreadable
files have a null SHA. No output files are created. Acknowledgement is a caller
assertion, not automatic detection of private data.

## Python entry points

```python
from apps.prepared_pipeline import prepare_file
from apps.prepared_pipeline.batches import PreparedInput, prepare_batches

batch = prepare_file(
    synthetic_csv_bytes,
    ".csv",
    synthetic_fixtures_only=True,
    reference_map=trusted_mapping,
    catalog=trusted_read_only_catalog,
)
summary = batch.workbench_summary()

collection = prepare_batches(
    [
        PreparedInput("synthetic-october-a", synthetic_csv_bytes, ".csv"),
        PreparedInput("synthetic-october-b", synthetic_jsonl_bytes, ".jsonl"),
    ],
    synthetic_fixtures_only=True,
    reference_map=trusted_mapping,
    catalog=trusted_read_only_catalog,
)
report_bytes = collection.json_bytes()
```

`prepare_batch` still accepts only the original strict prepared-intake JSON
envelope. `prepare_file` accepts CSV, JSON arrays/envelopes and JSONL. All formats
use the existing C1 adapters; they preserve original Arabic, combining marks,
RTL marks, Unicode separators, spaces, tabs and CR/LF within text. CSV reference
cells contain JSON lists, decoded only for matching. Original cells stay visible.
JSON/JSONL reference links must be actual lists. No title/question trimming occurs;
when both are present they must match exactly. Existing C1 export commands remain
available via `python -m tools.content_intake`.

## Results and bounds

Each preparation report retains every accepted or rejected parsed record with its
one-based ordinal, original fields, findings, reference outcomes and optional
receipt draft. Missing CSV cells retain null values and named findings. Extra CSV
cells are retained separately as `csv_extra_cells`, since they have no column name.
Malformed file syntax/envelopes are file errors; independent files still run.
Malformed files cannot contribute record identities to duplicate checks.

All occurrences of an exact duplicate external ID are blocked, including across
files; IDs are never renamed or Unicode-normalized. Duplicated C2 mappings receive
a pointer-indexed rejection instead of a generic constructor error.

`workbench_summary()` and report `workbench` expose record/draft counts, status,
finding and reference-outcome counts, plus row identities and separate rejection,
review and reference reasons. Collection `summary` adds batch/error counts and
batch identity on every row. Output is deterministic for fixed bytes, file order,
trusted mappings and catalog evidence. Preparation readiness describes receipt
eligibility; it does not establish reference verification or scholarly approval.

Mappings and catalogs come only from trusted caller arguments. `C1Pointer` and
`ExplicitMapping` retain the existing exact source-pin contract; payloads cannot
provide mappings or catalogs. Without them, links remain explicitly unverified.
The CLI accepts no mapping configuration from files.

Limits stay at 1,000,000 input bytes, 1,000 records and 100 links per record.
Collections also cap combined readable bytes/records and number of inputs at
those existing bounds. Text limits are external ID 100, question/notes/title
20,000, media URL 2,048 characters. C2 receipts require HTTPS on default/443 port;
C1 adapter validation retains its existing HTTP compatibility.

No migrations or PostgreSQL operations are introduced. Gate B NOT_PASSED; C/D/E
HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED.
