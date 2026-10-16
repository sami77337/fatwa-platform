# Fatwa Platform — integrated local reference catalog

NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED;
C/D/E HOLD; Phase01 BLOCKED; U03/U10 OWNER_APPROVAL_PENDING.

This integration worktree retains the S0 Django foundation and integrates the S1
source validator and S2 Arabic RTL interface. Django reads PostgreSQL through the
ORM. Implemented functions include lazy expandable trees, original-title Arabic
search with three modes and root scope, breadcrumbs, child/search paging,
edition selection, printed citations, keyboard controls and mobile layout.
Server-rendered navigation is available at /fiqh?basic=1.

Book 622 is one Hanbali reference work's table of contents, not a global fatwa
taxonomy or a corpus of approved fatwas. Private questions, account administration,
publishing, delivery and AI answers remain unavailable. The website does not use
S2's standalone synthetic fixture adapter. Empty databases display an empty catalog.

## Current observed state — 2026-10-15

**REAL_SOURCE_DATABASE_IMPORT=PASS; DJANGO_SITE_HTTP=PASS; REAL_CATALOG_HTTP=PASS.**
The genuine catalog is operational at **http://127.0.0.1:8000/fiqh**. It contains
11,397 headings, 32 roots and maximum depth 5, attributed to book 622 and the
Ministry of Justice edition.

The existing Git-ignored .local/host-result.json records a completed host import at
2026-10-15T11:35:19.996Z into fatwa_reference using fatwa_app on PostgreSQL 18.6:
checksum-pinned PREVIEW, IMPORTED, then an unchanged read-only comparison of all
persisted fields and counts. The import was already complete when this continuation
checked the live site, so no duplicate import or database write was performed.

This continuation independently rehashed the actual original ZIP and JSONL member,
then compared **all 11,397 live ORM-backed API records** against the source and the
independent original-title CSV. Every source ID, exact title, parent, sibling order,
source order, part, printed page and page ID matched. Every parent path and all
32 roots matched. Reconstructing the full live mapping reproduced the pinned
b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7 checksum.
The repeatable [read-only verifier](tools/dev/verify-live.mjs) saves its actual
summary to .local/live-verification.json; it preserves the earlier host report.

Direct Docker/Python access remains denied in this agent session. The direct SQL
and S1 execution evidence above comes from the saved host run, while the exhaustive
live source/API confirmation was executed here. See the precise
[acceptance evidence](docs/architecture/INTEGRATION_RESULT.md).

## One-click continuation on the owner's host

Open **[tools/dev/START_LOCAL.cmd](tools/dev/START_LOCAL.cmd)** from Windows Explorer
in the normal owner session with access to the existing Docker Desktop engine.
No sequence of PowerShell commands or host Python installation is required.
The runner uses the existing Node and Docker installations and writes its actual
result to the Git-ignored .local/host-result.json. Its window stays open for review.

The runner:

- Verifies the original archive SHA256 and the integration branch, then inspects
  the actual existing fatwa-site-v1 container and isolated S5 PostgreSQL 18.6 cluster.
- Requires the internal network fatwa-s5-dev-pg18_local, read-only code/secret
  mounts, application role fatwa_app and database fatwa_reference. It refuses
  unexpected roles, snapshots, networks, mounts or public port exposure.
- Starts only those same existing containers if stopped. It creates no replacement
  cluster, role or persistent volume and never changes Docker network isolation.
- Runs an ephemeral Python 3.13 worker using the site's inspected immutable image
  ID, offline pinned wheels from control/wheels/py313-linux and read-only mounts.
  Passwords are read inside the worker from /run/secrets/app-password.
- Executes the existing import_book622 validation and database PREVIEW inside a
  read-only transaction. It verifies 11,397/32/5, every original title, zero inferred
  titles and the exact mapped checksum before any import. A complete matching
  edition is confirmed read-only and the duplicate import is skipped.
- Applies only the validated preview checksum to an absent snapshot, then compares
  every persisted original field, parent, source ID and printed reference using
  read-only queries. It never deletes or repairs a conflicting snapshot.
- Runs S1 tests in tmpfs and Django/PostgreSQL tests with --keepdb only when the
  separate existing test_fatwa_reference_dev database is empty and contains only
  expected test tables. An absent or nonempty test database is reported NOT_RUN;
  it is never created, dropped or reset by this runner.
- Checks live HTTP metadata, all three search modes, depth-five paths, nested
  children, SSR fallback and rejected write methods. It also runs the frontend
  regression suite. Browser/mobile interaction remains a separate unexecuted check.

The runner never stages, commits, pushes, merges or deploys. It leaves the existing
site available only at **http://127.0.0.1:8000/fiqh**. If a previous interrupted run
left a lock or Docker configuration differs, it stops and records the blocker.
An import pass and an HTTP pass are reported separately from test failures.

The earlier [tools/dev/site.ps1](tools/dev/site.ps1) remains available for developers
with an accessible Python and loopback PostgreSQL. The current internal Docker
network requires the one-click container workflow above; localhost:55432 on Windows
is not a working database path in this environment.

## Source identity

Original ZIP: FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip, outside this worktree.

- Archive SHA256: 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce
- JSONL member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl
- JSONL SHA256: 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14
- Mapped checksum: b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7

Raw sources, exports, credentials, local results and environments are ignored by
Git. Upstream 622.db/title.zip were not supplied; their declared hashes remain
attribution, not independently verified upstream provenance.

## Verification and remaining limits

- Current real-source read-only acceptance: PASS for every live record and parent
  path, metadata, nested child paging, original-title search in all three modes,
  depth-five details, printed citations and server-rendered fallback.
- Current Node regressions: 36 PASS, 0 failures/skips. These include mock/synthetic
  tests and actual archive identity checks, separately from real catalog acceptance.
- Saved host S1 suite: 59 PASS, including the real JSONL, CSV and nested JSON source.
- Native Ruff: PASS for the integration Python scope and container worker.
  JavaScript syntax and git diff whitespace checks passed.
- Live boundaries: mutations rejected with 405; admin, fatwa and synthetic fixture
  asset routes return 404; invalid or duplicate query parameters return 400;
  the existing restrictive CSP is present.
- Django/PostgreSQL test suite: NOT_RUN in the host report because an accessible
  empty dedicated test_fatwa_reference_dev database was unavailable. This session
  could not rerun it because Docker pipes and the Python base executable are denied.
- Browser/mobile/keyboard acceptance: NOT_RUN. Fresh Chrome and Edge DevTools
  timed out at Page.enable before UI initialization; the connected browser tool
  reported no available browsers. HTTP and HTML checks do not substitute for this.

No commits, pushes, PR changes, merges, deployments, persistent resets, credential
changes or sibling-worktree changes were made. The local site remains available.

[S0 architecture](docs/architecture/README.md) ·
[S1 ingest contract](docs/data-ingest/S0_HANDOFF.md) ·
[Integrated API mapping](docs/ui-api-contract/INTEGRATED_DJANGO.md)
