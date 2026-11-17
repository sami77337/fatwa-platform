# V9 lane B — reviewed knowledge relationships

Base verified twice: PR #227, `81ccdb0f0fd25521e61ed65f098a124324139967`.
Owned branch: `codex/20261117-v9-knowledge`. Only `apps/knowledge_links/**` changes.
No shared config, templates, citations, publications or transcript applications edited.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED / ACCEPTANCE_HOLD.**
Synthetic development only; no U03 permission grants, real data, external requests,
AI approvals, deployment, main merge or child PR.

## What works

- Propose a relationship from an independently approved, current experimental
  publication edition to an exact reference heading already cited by that edition,
  or an existing transcript question linked to the same canonical case/evidence.
- A different scoped human MUFTI with explicitly configured knowledge authority
  approves the exact relationship revision. No inferred semantic associations.
- Inspect proposed reference metadata or privately authorized transcript question
  before approval. Proposals never appear in the library's linked-material search.
- Browse/search approved reference metadata with the existing Arabic normalization;
  show book, edition, publisher, printed part/page and hierarchy. Open and return
  to the same publication/query using native CSRF-protected forms, without return URLs.
- Open the transcript question's exact source ID, pair and millisecond range only
  after a fresh `OPEN_TRANSCRIPT` grant. No transcript answer is imported as a ruling.
- Append corrections and withdrawal events. New corrections immediately hide the
  preceding revision until separately approved; withdrawal never resurrects it.
  Private audit remains accessible to scoped staff after publication withdrawal.
- PostgreSQL rejects updates/deletes of relationship/action rows, inconsistent
  publication/source/case bindings, nonsequential revisions and self-approval.
  Service writes serialize on the existing canonical case lock, recheck identity
  after processing and never create answer/evidence/delivery records.

The library projection contains approved publication text and existing cited source
metadata, plus a generic transcript-link label. It never contains original question,
transcript text/source IDs, case reference, actor, private rationale or audit events.
Searching private strings cannot match them. Audit and preview are separate private
staff operations, never public-library response fields.

## Integration contract (integrator-owned changes)

1. Add `apps.knowledge_links` to the synthetic campaign's `INSTALLED_APPS` and run
   migrations `knowledge_links.0001_initial` / `0002_integrity`. App templates are
   discovered through the existing `APP_DIRS=True`; no shared template override.
2. Keep `FATWA_KNOWLEDGE_LINKS_ENABLED=False` and
   `FATWA_KNOWLEDGE_LINKS_AUTHORITY=None` by default. Synthetic demo/tests may opt in,
   alongside existing casework, publication and citation feature flags. Every
   service still requires `FATWA_PRODUCTION=0`, explicit synthetic acknowledgment,
   owned PostgreSQL and the existing trusted identity provider.
3. In the existing `/casework/staff/` dispatcher, route POST actions in
   `apps.knowledge_links.views.ACTIONS` to `workspace` before its ordinary fallback.
   Keep the existing CaseworkGuard, loopback restriction, CSRF, private cache headers
   and request identity provider. No new route or guard relaxation is needed.
   `apps.knowledge_links.urls` is the isolated composition demonstrating this.
4. Add a native form to the authorized publication detail with CSRF, action
   `knowledge_browse`, `publication_id={{ edition.id }}`, and `query=""`.
   This lane deliberately does not change the publication template. For historical
   editions a private staff history entry may use `knowledge_history` with the same
   fields; it does not open withdrawn publication content or live source material.
5. Configure a server-owned subclass of `KnowledgeAuthority`. `permits` receives
   provider ID, subject ID, current auth epoch, exact case ref, action and kind.
   Actions are `APPROVE`, `WITHDRAW`, `OPEN_TRANSCRIPT`; kinds `REFERENCE`, `TRANSCRIPT`.
   Only literal True grants access; exceptions, missing authority and false deny.
   This is an additional development permission contract, not production policy.
   Test authorities in `tests.py` must not become application defaults.

All actions require `action`, `publication_id`, `query`, plus CSRF. Extra fields:

| Action | Fields | Result |
|---|---|---|
| `knowledge_browse` | none | approved current links / Arabic search |
| `knowledge_desk` | none | private candidates and version history |
| `knowledge_propose` | `kind`, `target_id`, `reason`, `replaces_id` (blank for new series) | proposed revision |
| `knowledge_preview` | `revision_id` | private proposed/current source preview |
| `knowledge_approve`, `knowledge_withdraw` | `revision_id`, `confirm=yes` | append action |
| `knowledge_open` | `revision_id` | current approved material only |
| `knowledge_history` | none | private immutable historical snapshots/actions |

`target_id` is the existing ReferenceHeading PK for REFERENCE, or TranscriptLink
UUID for TRANSCRIPT. `desk()` supplies the actual candidates; never derive IDs from
matching titles. The reference must equal a source snapshot in PublicationEdition.
All navigation rechecks current publication approval, evidence, citation fingerprints,
relationship revision and source identity. A new publication edition inherits no links.
Service interfaces live in `services.py`: `propose`, `act`, `browse`, `desk`,
`preview_material`, `open_material`, `history`; identity/provider arguments are trusted
server inputs, never HTTP form authority.

Locked read adapters intentionally reuse existing internal source validation:
`case_citations._source`, publication validation/projection and
`transcript_case_links._entries/_check_link`. Their public read APIs open a
pre-transaction ownership guard and cannot be nested under the canonical case lock.
No guards are monkeypatched or bypassed. These internal adapter dependencies should
be versioned together if the integrator changes upstream contracts.

## Tests and evidence

Python **3.13.5**, Django **5.2.18**, fresh isolated **PostgreSQL 17.12**.

- PASS **14/14** focused service/PostgreSQL/HTTP tests, followed by PASS **2/2** added
  HTTP full proposal/preview/independent review/withdrawal and mid-read identity
  revocation tests. The initial 14 were unchanged; no unrelated suites rerun.
- PASS **1/1 Chromium 154.0.8037.57** browser journey on PostgreSQL 17: RTL at 320 and
  1280 pixels, keyboard focus, no horizontal overflow, reference location,
  authorized transcript open and query-preserving return. Zero page errors and
  zero external requests. Local browser used explicit `chromium_sandbox=False`;
  sandboxed Chrome and combined-head PG18 verification belong to integration.
- Both new migrations applied to fresh owned PostgreSQL. System check, migration
  drift check, Ruff and diff whitespace check are recorded with the final delivery.
- Historical development failures retained: first run 10 errors from nesting an
  upstream pre-transaction guard; fixed by the locked read adapter. Second run had
  two failures: an overbroad assertion mistook the source's `publisher` metadata key
  for an actor disclosure, and ValueError handling intercepted CaseConflict before
  its 404 handler. Both corrected; search now uses meaningful source values only.
  An intermediate preview refactor produced five NameErrors in browse and one Ruff
  error; corrected before the passing 14-test run. No remaining known test failure.
- Initial migration generation warned that the deliberately unreachable default
  database port 1 was unavailable; real fresh PostgreSQL migration/test runs followed.
- **NOT RUN here:** PG18, production/real data, real source rights policy, full
  campaign integration, sandbox-enabled Chrome. Earlier V8 failures/evidence remain
  unchanged in their original documentation; these results do not supersede them.

Reproduce (PostgreSQL binaries supplied by the executor, no production connection):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.knowledge_links.settings -- \
  python manage.py test apps.knowledge_links.tests

FATWA_TEST_BROWSER_NO_SANDBOX=1 \
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.knowledge_links.settings -- \
  python manage.py test apps.knowledge_links.browser_tests
```

The browser harness requires Playwright 1.58.0 plus Chromium in the executor; no
shared dependencies changed. The standard synthetic PG helper initializes and
removes the isolated cluster. Local browser artifact: `.local/qa/knowledge-links/browser.json`.

## Limits

Book 622 remains one source-book TOC, not a fatwa corpus or full-text reference.
Existing transcript sources have source/pair IDs and question time ranges; there is
no independent canonical Lesson model or licensed recording player here. The UI
therefore labels the real lesson/transcript source and does not invent a lesson,
recording URL, title, quotation or scholarly relationship. References not yet cited
by the approved publication must go through the canonical answer/citation/publication
workflow first. Rights to real materials and production audience policy remain blocked.

Bounded development capacity: 32 relationship series per publication, 64 revisions
per series, 80-character search and 1,000-character private rationale. The existing
library scans at most the identity's scoped cases; this is not a large-corpus index.
Search covers linked reference metadata, not private transcript content. The history
UI is an audit, not proof that old sources are still available. Shared library entry
buttons, shared dispatcher/config and unified campaign journey remain integration
work explicitly outside this lane's ownership.
