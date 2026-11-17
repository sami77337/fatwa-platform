# V9 lane C — research workspace receipt

Base: PR #227, `81ccdb0f0fd25521e61ed65f098a124324139967`, verified through GitHub PR
metadata and `git ls-remote` before checkout. Branch: `codex/20261117-v9-research`.
No main checkout/merge, production deployment, real data, outside messages or
sub-PR. Only `apps/case_citations/**` was changed; no new app was needed.

Read: root AGENTS.md, V8 campaign/citation contracts and tests, V6 scope trace,
and current owner decision log (including D-068/069/072). `.agents/skills` was
absent. Current delegated V9 ownership/branch instructions supersede historical
lane/PR instructions without editing AGENTS.md.

## Delivered

Source preview/return preserves unsaved text and filters; Arabic candidate
suggestions reuse authorized catalog search and require explicit human selection;
keyboard ordering and editorial notes persist on new answer revisions. Corrections
link immutable old/new citations, reason, answer author and timestamp; history is
paged and distinguishes current source availability from historical evidence.
All saves retain V8 files and force fresh human approval/private availability.
No automatic fatwa, invented quotation, new source corpus or scientific confidence
claim. Source 622 remains one book's title index.

## Executed evidence — Python 3.13.5, isolated PostgreSQL 17.11

- PASS **15/15** existing affected citation service/composer/preservation tests.
- PASS **11/11** new research service/form tests after fixes, covering suggestion
  purity, source preview/return, ordering/notes, correction chains, stale facts,
  revoked scope, SQL immutability/late insertion, rollback, and retained actual
  file bytes/hash with approval/private availability invalidated.
- PASS **1/1** additional direct-database cross-case forgery test, added after the
  group above; rejected inside the new answer transaction and rolled it back.
- PASS **1/1 Chromium 154.0.8037.57** browser journey on PG17. RTL at 320/1280,
  keyboard submit, Arabic proposals, preview/return, reorder, correction/history,
  persistent draft, zero external HTTP requests and zero page errors. Local run
  explicitly `FATWA_BROWSER_SANDBOX=0`; no sandboxed-browser claim.
- PASS database-backed migration drift check (`No changes detected`), system
  checks from test runner, Ruff, and `git diff --check`.
- NOT_RUN: local PostgreSQL 18, sandboxed Chrome, unified campaign journey and
  final aggregate CI. The integration owner runs those on the unified head.

The suites above are recorded separately. Existing unrelated suites were not
selected for a manual campaign-wide rerun. Initial new-suite discovery imported
14 old test cases inadvertently; module imports were corrected before the focused
11-test rerun. The final new service/form module contains 12 tests.

Historical failures retained: initial research run had one failure/three errors
from the PostgreSQL alias `old` conflicting with PL/pgSQL `OLD` and a test using an
incorrect AnswerPart relation. Alias and test fixture were corrected; the focused
rerun passed. First browser run failed on a synchronous ORM read inside Playwright's
async context; DB assertions moved outside that context, then the browser passed.
Initial makemigrations generation reported the expected disconnected default DB;
actual isolated DB migration/drift checks later passed. No known remaining local
failure. No prior V8 or historical acceptance evidence was changed.

## Integration and remaining limits

Apply the two new citation migrations; existing campaign registration and staff
`citation_compose` dispatch already suffice. No shared files need edits for this
lane. See README for the optional `corrections` service argument, paged private
history projection, and proposal status/method. Keep cross-editor clone calls in
their existing authorized case transaction. Public callers must not expose the
staff history projection or treat proposals as approved relationships.

Suggestions and unsaved notes are temporary signed browser-bound state (30 minutes),
not persistent research collections. Sources are existing authorized catalog
metadata, not full text; future source-rights providers or lesson/transcript
adapters must be integrated through their owners' contracts. Organizer/researcher
permissions await accepted policy; this lane grants none. Existing quote/script
strings in synthetic fixtures are escaped literally, including in history.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED /
ACCEPTANCE_HOLD.** No completion percentage or owner acceptance is inferred.
