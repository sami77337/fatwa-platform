# A4 — verified book-622 read-only source QA

**NON_PRODUCTION_LOCAL_CHANGES / NOT_DEPLOYED / GATES_HOLD**

Base commit: d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe.
Branch: codex/site-functions-20261015-181420-c415-a4.
This snapshot already contained integrated, uncommitted changes when A4 started.
Only A4-owned paths were edited. No commit, push, PR, deployment, Docker command,
DB import, migration, reset, delete or source archive modification was performed.

Book 622 is one Hanbali reference work's Ministry of Justice edition TOC, not a
fatwa corpus or a global taxonomy. Gate B remains NOT_PASSED, Gates C/D/E HOLD,
Phase01 BLOCKED, and U03/U10 remain pending owner acceptance.

## Changes

- audit_book622 reuses the pinned ZIP validator and existing S1-to-S0 mapping.
  It verifies the source before opening a DB connection, then compares every row
  even when the stored checksum matches: both ID namespaces, exact original
  Arabic, parent ID and parent edition, source order, sibling position, depth,
  printed part/page, page ID, entry number and derived search title. Work/edition
  metadata, hashes and actual 11,397/32/5 totals are checked too.
- PostgreSQL enforces REPEATABLE READ / READ ONLY before the first ORM query.
  Commands refuse nested/manual transactions, non-PostgreSQL connections and
  versions outside 17/18. All reads use one consistent snapshot. Diagnostics
  contain IDs and field names, with a 1–100 sample limit and full issue counts.
  Scanning is capped at 20,000 rows plus one sentinel; oversized snapshots fail.
- The optional --heading-id retrieves one citation through existing services
  after a successful full audit, preserving the original title and printed
  reference and returning at most five ancestors. No new public endpoint, source
  export, upload, import, create or repair option was added.
- benchmark_reference uses the same read-only snapshot and verifies historical
  edition pins and actual/stored 11,397/32/5 totals. It measures materialized roots
  and search pages plus a bounded citation path, recording returned items and
  total matches alongside timings/query counts. A page of 30 is explicitly
  distinct from all 32 roots. Connection setup, snapshot checks and HTTP are
  excluded. A benchmark is explicitly not a source fidelity audit.
- ZIP/archive members are read with bounded decompression. The reviewed mapped
  checksum is pinned as well as archive, JSONL and original-title CSV hashes.
  Historical root ID sets are frozen. Existing preview/default and explicit
  checksum-before-apply behavior is preserved; the write path was not executed.

## Coordinator verification on the reviewed integrated site

Use a checkout containing reviewed A4 changes, a working Python 3.13/Django
environment and the existing reviewed PostgreSQL 17/18 connection. Supply the
original archive through its approved path; do not copy source into Git or public
directories. Replace the placeholders with the actual archive path and edition ID.

~~~powershell
# Source-only verification: no DB access and no import.
py -3.13 -B manage.py import_book622 --archive "<trusted-original-zip>" --validate-only

# Complete comparison and optional single bounded citation.
py -3.13 -B manage.py audit_book622 --archive "<trusted-original-zip>" --edition <existing-edition-id> --heading-id 1 --max-issues 20

# Actual bounded ORM measurements, after successful audit.
py -3.13 -B manage.py benchmark_reference --edition <existing-edition-id> --query "كتاب" --heading-id 1 --repeats 5
~~~

Expected audit success: exit 0, valid=true, database_audit=EXACT_MATCH,
matched_rows=11397, actual_roots=32, actual_max_depth=5, scan_complete=true,
issue_count=0, database_import=NOT_RUN. A mismatch emits bounded JSON diagnostics
and exits nonzero without repair. A missing archive, edition or DB is an error;
no replacement is created. Tie evidence to the reviewed SHA and working diff,
source hashes, edition ID and actual PostgreSQL version.

The general host/start workflow can import if a snapshot is absent; do not use
it for this verification. The commands above require the already existing DB.
Use standard unittest below, not manage.py test, so no test database is created,
migrated or destroyed.

~~~powershell
# Synthetic/negative tests; original-source tests skip if source is absent.
py -3.13 -B -m unittest discover -s tests/fiqh_import -v

# Mocked commands; existing-DB acceptance skips without explicit opt-in.
py -3.13 -B -m unittest discover -s tests/integration/source -v

# Explicit optional read-only acceptance against the existing reviewed edition.
$env:FATWA_622_ARCHIVE = "<trusted-original-zip>"
$env:FATWA_622_AUDIT_EDITION = "<existing-edition-id>"
py -3.13 -B -m unittest discover -s tests/integration/source -v
~~~

The opt-in test subclasses unittest.TestCase, never Django's database TestCase.
It calls audit_book622 twice, verifies all 11,397 matches and repeatability, and
checks a bounded citation. It never invokes persistence or a test DB lifecycle.
Mocked tests use synthetic seven-node data, not real PostgreSQL/source evidence.

## Historical identities

These pins are inherited from repository evidence. They were not recomputed
from the original in A4: the trusted archive is absent inside this worktree.

| Identity | SHA256 |
| --- | --- |
| FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip | 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce |
| FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl | 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14 |
| FATWA_622_FIQH_COMPLETE/622_العناوين_الأصلية_ID_title.csv | 13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9 |
| Existing reviewed mapped snapshot | b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7 |

Edition key: 622-moj-owner-r1-20261011. Historical roots are the two introductions
(IDs 1 and 23) and the existing 30 reviewed fiqh-book IDs. No title classification
or source inference was added. Upstream 622.db/title.zip remain unsupplied; their
declared historical hashes are not independently verified upstream evidence.

## Actual A4 execution

- Both unittest commands above were attempted: exit 112, stderr
  "No installed Python found!". No test loaded; no passing/failing/skipped count
  is claimed. There are 33 new methods: 31 synthetic/mocked regressions and two
  optional acceptance methods. Those are defined methods, not executed tests.
- py -0p returned "No installed Pythons found!". The known Python313 executable
  could not launch. No runtime was downloaded or installed.
- git diff --check returned exit 0 with existing LF/CRLF notices. A separate
  file-level whitespace scan covers untracked A4 files. Neither is a Python
  syntax check or a substitute for executed tests. An additional nondefault
  core.autocrlf=false diff check returned exit 2 because it treats the inherited
  CRLF checkout as whitespace differences across the repository; those files
  were not modified by A4.
- Source validation, original-source acceptance, actual DB audit, benchmark and
  live citation QA are NOT_RUN in A4. Owner site-v1, sibling worktrees and DB
  volumes were not accessed to fill this gap.

[execution-evidence.json](execution-evidence.json) records exact command results
and current code/fixture hashes. The earlier successful local import remains
prior coordinator evidence; A4 neither repeated it nor independently accepted it.
