# S1 — standalone book 622 heading ingestion

> A4 (2026-10-15): current read-only audit, coordinator commands and exact execution limits
> are in [docs/dev/a4](../dev/a4/README.md). Original-source availability and runtime
> claims below are historical S1 evidence, not results from this isolated A4 snapshot.

**NON_PRODUCTION_LOCAL_CHANGES / NOT_DEPLOYED / GATES_HOLD**.
Gate B NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED. This package validates
heading metadata for one Hanbali reference work. It does not establish a global
fatwa taxonomy, publish rulings, grant permissions, or process private cases.

Issue #2 owns this package, tests and documentation. Runtime is Python 3.13,
standard library only: no pip install, Django imports, database writes, network
requests, scraping or execution of scripts from the source archive.

## Commands and execution status

From the repository root with Python 3.13 installed:

~~~powershell
py -3.13 -B -m unittest discover -s tests/fiqh_import -v
New-Item -ItemType Directory -Force tests/fiqh_import/.scratch
py -3.13 -B -m tools.fiqh_import --input tests/fiqh_import/fixtures/synthetic-five-level.json --manifest tests/fiqh_import/fixtures/synthetic-five-level.manifest.json --profile synthetic --output tests/fiqh_import/.scratch/synthetic.jsonl --report tests/fiqh_import/.scratch/synthetic.audit.json
~~~

A copy of the verified owner's JSONL member is present locally in the ignored
scratch directory. After runtime setup, validate it with:

~~~powershell
py -3.13 -B -m tools.fiqh_import --input tests/fiqh_import/.scratch/owner-622-r1.jsonl --manifest docs/data-ingest/owner-622-r1-jsonl.manifest.json --profile real-622 --adapter owner-622-r1 --output tests/fiqh_import/.scratch/owner-622-r1.normalized.jsonl --report tests/fiqh_import/.scratch/owner-622-r1.audit.json
~~~

On Linux/macOS replace `py -3.13` with `python3.13`; create scratch with
`mkdir -p tests/fiqh_import/.scratch`. No source ZIP, raw source, generated export
or runtime binaries should be added to git. Tests read the local owner ZIP when
present, otherwise explicitly skip real acceptance with SOURCE_DATA_MISSING.

These commands are reproducible instructions, **not a passing Python test claim**.
The current machine has no installed Python. See [true execution results](TEST_RESULTS.md)
and [independent source inspection](source-inspection.json). The Node checks
verified source integrity; they did not execute the Python importer or prove its
rerun behavior. No normalized output SHA256 is asserted here.

## Canonical input

UTF-8 CSV, JSON arrays, and LF-delimited JSONL are supported. An initial BOM is
allowed and included in the input hash. The suffix chooses the format; override
with `--format csv|json|jsonl`. Default adapter is `canonical`; it accepts only
the [canonical heading fields](../../tools/fiqh_import/schemas/input-heading.schema.json).

| Field | Rule |
| --- | --- |
| `id` | Required nonblank string, preserving lexical IDs such as "0007". No padding or control characters. |
| `parent_id` | Required string or JSON null for a root; CSV uses an empty root-parent cell. |
| `title` | Required nonblank valid Unicode; preserve original spaces, spelling, punctuation and diacritics. |
| `sibling_order` | Required nonnegative integer or ASCII digit string; unique among siblings, including roots. Gaps are allowed. |
| `part` | Positive integer/digit string, or the actual source edition's named volume label `المقدمة`. This label is preserved, never assigned a fabricated numeric volume. |
| `page` | Required positive integer/ASCII digit string. No blank values, booleans, fractions, ranges, signs, Arabic digit forms or zero. |
| `title_origin` | Explicit direct/inferred; no title generation or automatic scholarly inference. |
| `inference_evidence` | Nonblank supplied string required for inferred titles; absent/null for direct titles. |
| `edition`, `provenance` | Optional nonblank per-heading overrides, otherwise inherited from the pinned manifest. |
| `root_kind` | Optional introduction/fiqh_book, only on roots. All real-profile roots need a kind. |

Unknown fields, duplicate JSON keys, non-finite numbers, malformed UTF-8 and
unpaired surrogates are rejected. CSV requires unique headers and equal field
counts and supports quoted multiline titles. Blank JSONL records are rejected.
Source strings are data; consumers must escape them in HTML.

Limits: 64 MiB input, 64 KiB manifest, 100,000 records. Numbers use signed 64-bit
bounds; numeric strings are limited to 18 characters. CSV also uses the stdlib
default field-size limit. Graph traversal and cycle checks are iterative.

## Supplied owner export adapter

`--adapter owner-622-r1` explicitly selects the observed 2026-10-11 export:
flat CSV/JSONL or nested JSON with a roots/children hierarchy. It accepts the
source's exact fields, rejects unknown columns and preserves original typed IDs,
printed references, source_page_id, path metadata and Lucene title keys in
`source_metadata`. Canonical source_id/parent_id are strings; the original numeric
JSON IDs or CSV strings remain available in that metadata.

Mapping: position_among_siblings (nested JSON: order) → sibling_order;
source_part → part/source_part; source_page_number → page/source_page.
Nested child membership must agree with explicit parent_id. Declared depths,
child counts and leaf flags are checked against actual edges.

The owner archive's original-title CSV independently matched all 11,397 names
and IDs. This edition adapter identifies supplied labels as direct, verifies
flat-row title keys as "622-" plus the heading ID, and uses the fixed source root
IDs: 1 and 23 are introductions; the remaining 30 documented roots are fiqh
books. It does not classify by title wording or invent missing headings.
Real-profile execution additionally requires the exact observed source-member
SHA256 for the selected format, so reworded/re-pinned files cannot pass this
specific edition adapter.

## Manifest, profiles and completeness

Every run requires a [manifest](../../tools/fiqh_import/schemas/manifest.schema.json)
with exactly: dataset_id, source_kind, book_id, edition, provenance, input_sha256,
expected_nodes, expected_roots and expected_max_depth. See the synthetic fixture
manifest and [owner JSONL manifest](owner-622-r1-jsonl.manifest.json) for valid
examples. book_id must be "622"; all expected totals are positive integers.

SHA256 covers the exact input bytes, including BOM and line endings. A manifest
is a trusted caller's provenance assertion, not a rights grant, signature or
proof of upstream SQLite/Lucene verification. The owner adapter's member pins
establish identity with the supplied ZIP; that ZIP's upstream database/index
hashes are declarations, since those upstream files are not in this workspace.

The synthetic profile requires source_kind=synthetic and explicit completeness
totals. Real-source acceptance is always NOT_RUN and the report says
SYNTHETIC_ONLY_SOURCE_DATA_MISSING. It cannot downgrade owner-supplied validation.

The real-622 profile requires source_kind=owner_supplied and fixed totals:
**11,397 unique titled nodes, 32 roots, depth 5**, with **30 fiqh_book and two
introduction roots**. These cannot be weakened through the manifest. Duplicate
IDs, orphans, cycles, unreachable nodes, blank titles, missing/invalid page
references and ambiguous sibling orders fail validation. Success means
STRUCTURE_VALIDATED, never owner policy acceptance or production approval.

The actual supplied ZIP is:
`_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip`.

Its independently verified archive SHA256 is
`82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce`.
The inspected JSONL member SHA256 is
`37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14`.
Source inspection confirmed the full original ID/title set, 32 roots, maximum
depth 5 and all 11,397 reachable nodes. No archive scripts were executed and no
source has been committed. Python acceptance remains blocked by its runtime.

## Strict mode, diagnostics and deterministic export

Normal execution is strict: validation failure returns exit 1 and writes no
heading export. Dry-run reports issues, still exits 1 on invalid input, and
never writes an export. Use `--dry-run --report ...` for an optional diagnostic
artifact; dry-run cannot be combined with --output. Invalid CLI usage exits 2.

A valid input may arrive in arbitrary record order. input_topological reports
the observed ordering; output is parent-first preorder, following original
sibling order, with output_topological=true and the full reachable set.

The [fiqh-toc.v1 output schema](../../tools/fiqh_import/schemas/output-heading.schema.json)
defines UTF-8 JSONL without BOM, sorted keys, fixed separators and one LF per
row. Reports contain actual input/output SHA256, counts, provenance, direct/
inferred totals and every validation issue. There are no timestamps, random
identifiers or absolute paths in valid exports. The same exact bytes and manifest
are intended to produce byte-identical reruns; Python tests will verify this
when a runtime is available.

Original title remains verbatim. search_title alone derives NFKC, removes
combining marks/tatweel, folds alef variants and alef maqsura, collapses whitespace
and case-folds. Original part/page representations survive separately from their
lookup values; named introductory volumes remain strings.

Exports and reports each use atomic replacement; their parent directories must
exist. Validation failure preserves previous output. The CLI refuses source/
manifest/report aliases, hardlink collisions and symlink output targets.
The two artifacts are separate writes; S0 must verify their matching hashes.

See [S0 handoff](S0_HANDOFF.md) for the database-free integration boundary.
