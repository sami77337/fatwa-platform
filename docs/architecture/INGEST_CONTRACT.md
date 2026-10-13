# S1 -> S0 development ORM adapter

Entry point: apps.reference.ingest.ingest_catalog(spec, records, *, dry_run=True,
expected_checksum=None). It accepts CatalogSpec and a Sequence[HeadingRecord]
from apps.reference.records. It never opens archives or parses source formats.
The command/parser/validator stays owned by S1. No HTTP import route exists.

## Mapping contract

| S1 validated metadata | S0 field |
|---|---|
| Source namespace and book ID | CatalogSpec.source_namespace / source_book_id |
| Original work title / madhhab | work_title / madhhab |
| Reviewed edition identity/title/publisher | edition_key / edition_title / publisher |
| Verified original archive SHA-256 | source_archive_sha256 |
| Verified exact input member SHA-256 | source_input_sha256 |
| Logical member basename, never local path | input_name |
| Validated rows, roots, max depth | expected_rows / expected_roots / expected_max_depth |
| Original lucene_title_key (e.g. book-row identity) | HeadingRecord.source_id |
| Original id | source_row_id |
| Original parent_id, null for roots | parent_source_row_id |
| Original global source input row order, 1-based | source_order |
| position_among_siblings | position |
| depth, root depth 1 | depth |
| source_page_id / source_part / source_page_number | same names |
| source_entry_number, may be null | same name |
| Original title, without rewriting/trimming | title_original |

source_order must come from the validated original row sequence, not a newly
sorted title list. S0 retains position separately. Parent references are source
row IDs, scoped to the edition; generated ORM primary keys are internal.

The supplied JSONL input has 11,397 observed lines; observed maximum original
title length is 198 characters and part length 7. S0 bounds original titles at
500 characters, normalized text at 2,000, and part text at 100, rejecting longer
records rather than truncating. It supports at most 20,000 rows and depth 5.
Source page IDs are required positive integers; printed part text stays a string.
The 500-character original-title bound keeps the UTF-8 exact-title B-tree key
within PostgreSQL's key size for supported source records.

For the reviewed book-622 snapshot, S1 must assert the exact 11,397/32/5 profile
and compare every original title/ID against independent original-title data.
S0 checks only persistence invariants: nonempty fields, complete mapped counts,
unique identities/order/sibling positions, parent presence and strict depth.
Those checks do not replace S1 archive/source verification or rights review.

## Two-phase call

~~~python
from apps.reference.ingest import ingest_catalog

# spec and records have already passed S1 source verification.
preview = ingest_catalog(spec, records)  # no inserts, updates or deletes
result = ingest_catalog(
    spec, records, dry_run=False, expected_checksum=preview.checksum,
)
~~~

The returned immutable IngestResult has dry_run, unchanged, checksum,
heading_count and edition_id. A new dry run has edition_id=None. The SHA-256
checksum pins canonical schema-v1 mapped spec/records, including every title,
parent, locator and source-order field. Normalization is derived for search only.
A commit without the exact preview checksum is rejected before writing.

Commit uses an atomic transaction and locks the work row, serializing concurrent
imports for the same source. New parents are inserted before their children;
any insert failure rolls the entire work/edition/snapshot back. No conflicts
are silently skipped. Existing work and edition metadata and every stored
heading must match on rerun. Changed/incomplete snapshots raise CatalogConflict;
a changed source requires a separately reviewed new edition key. Existing
snapshots have no automated repair/update/delete path.

CatalogConflict extends InvalidCatalog. Persistence/integrity failures propagate
rather than becoming fake success. The adapter requires PostgreSQL; there is
no SQLite fallback. S1/S5 must keep parser/DB audit output outside tracked data
and expose no raw source data or private exports in the PR.

## Supplied local input identities

- FATWA_BUILD_SPRINT_01_R2_20261011.zip:
  2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b.
- FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip:
  82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce.
- Inspected JSONL member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl;
  SHA-256 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14,
  matching its manifest. Source archive/member identity is verified; full original
  source validation and ORM import have NOT_RUN here. No source script executed.

The only committed test inputs are small hand-authored synthetic records in
scoped test code. Their placeholder hashes identify no owner-source acceptance.
