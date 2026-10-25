# Consolidated synthetic editorial exports

Development only, read-only, offline. Built on the FAST3 candidate PR #106 at
`a149b39bfd624e330762459a7c3e0b4febc7187b`; no database or migration is needed.
Existing preparation and case-packet services remain authoritative. Only their
fixed invented fixtures are included: 20 cases and four preparation batches.
No input paths, uploaded records, persisted review events or owner archives are
accepted. No AI, network, publication or scholarly decisions are performed.

## Use

From the repository root with Python 3.13 (the pure CLI also works without Django):

```powershell
python -m apps.editorial_export export --synthetic-fixtures-only --output C:/temp/new-editorial-export
python -m apps.editorial_export verify --synthetic-fixtures-only --input C:/temp/new-editorial-export
```

The parent output directory must exist; the output directory must **not** exist.
All files use exclusive creation. Source files are never opened for writing.
An I/O error can leave a partial new directory; verification rejects it. Choose
a fresh output directory after failure; the CLI never deletes or overwrites files.
Exit codes: 0 success, 1 guard/data/filesystem/replay failure, 2 CLI usage error.
Known rejected synthetic rows do not make a complete export fail: their exact
failure and recovery evidence is the requested report content.

For the existing loopback Django development server, open
`/dev/editorial-export`. It lists inventories, source identities, packet links,
file sizes and digests. Download endpoints are `/dev/editorial-export/report.json`,
`cases.csv`, `batches.csv`, and `manifest.json`. GET/HEAD only; queries and arbitrary
filenames are rejected. Existing guards reject non-loopback peers/hosts and
production configuration before loading fixtures. Downloads are attachments with
`no-store`, `nosniff`, and `X-Export-SHA256` for the actual response bytes.

## Files and exactness

- `report.json`: complete case packets, their canonical packet SHA-256, exact
  navigation keys/paths, and all preparation batch overviews including raw input.
  The malformed zero-row batch remains in inventory with its original digest,
  `MALFORMED_INPUT` and recovery reason. Snapshots, comparisons, technical reference
  findings, preparation errors and recovery reasons come from existing services.
- `cases.csv`: `navigation`, `packet`, `packet_sha256` columns. Complete packet
  objects are preserved, including immutable revisions and exact original fields.
- `batches.csv`: one row for each preparation batch, including zero-row failures.
- `manifest.json`: SHA-256 and byte count of the other three files, all batch input
  identities, and per-case exact identities/source kinds/packet digests. It does
  not recursively hash itself. HTTP exposes its own digest; save it separately if
  needed. Digests detect changes; they are not signatures or scholarly approval.

CSV is UTF-8 without BOM with quoted RFC4180 cells and CRLF record endings.
**Every data cell contains canonical JSON**, including strings, numbers and null.
Decode with `csv.DictReader` then `json.loads(cell)`. This preserves types, Arabic
diacritics, decomposed Unicode, surrounding spaces and embedded CR/LF; text cells
start with a JSON quote instead of formula operators. Do not strip quotes or
interpret source content as executable spreadsheet formulas. Headers are plain
fixed field names. JSON uses sorted keys, strict UTF-8, no floating point values,
no clock, no normalization, and a terminal LF. Nothing is silently truncated.

Batch order is exact `batch_id` lexical order; case order is exact `case_key`
lexical order. Nested packet arrays retain authoritative service ordering,
including reference ordinals and noncontiguous revision numbers. Never join by
external ID: duplicate, absent and invalid external IDs remain distinct cases.
Original intake byte slices, serialized history intake and parsed batch-row
serialization remain separately labeled; parsed rows are never called original
byte slices. Base cases have no preparation batch; no synthetic batch association
is invented for them. Reference matches are technical fixture matches only.

## Bounds and replay

Hard limits: 64 cases, 16 batches, 2 MiB per file, 6 MiB per bundle; serializer
100,000 nodes, depth 24, 131,072 characters per string and signed 63-bit magnitude
integers. Existing per-packet limits also apply. Exceeding a bound fails the whole
export. CLI verification enumerates only the four named regular files, rejects
symlink/reparse entries and extra/missing files, and bounds every read.

Verification rebuilds the fixed services for the checked-out code version and
compares all four files byte for byte, including the manifest. It does not trust
or deserialize an external manifest. Updating a tampered artifact's hash in the
manifest cannot bypass replay. Use the same commit for future replay; fixture or
schema changes intentionally invalidate older bundles. This is not a generic
importer, an archive authenticity check, or verification of real fatwa content.

## Focused verification

```powershell
python manage.py test tests.editorial_export.test_services tests.editorial_export.test_cli tests.editorial_export.test_views tests.editorial_workbench.test_packets tests.editorial_workbench.test_packet_views tests.editorial_workbench.test_batches tests.prepared_pipeline.test_batches tests.prepared_pipeline.test_pipeline --settings=config.settings.test --noinput
python -m ruff check apps/editorial_export tests/editorial_export
python -m ruff format --check apps/editorial_export tests/editorial_export
python manage.py check --settings=config.settings.test
```

These tests use real fixed synthetic services and Django `SimpleTestCase`, without
database access. They do not claim PostgreSQL, owner-ZIP or production acceptance.
No dependencies, migrations, settings, protected sources or other lane apps change.
Rollback consists of reverting the new module/templates/tests and one URL include.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD.**
