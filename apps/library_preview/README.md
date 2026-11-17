# V10 C — connected synthetic library preview

Base verified on GitHub and remote: PR #228 at
`12840d54c263e63b214ce72eff1d8b4f93f9900e`.
Branch: `codex/20261117-v10-library`; all changes inside `apps/library_preview/**`.
The earlier V9 branch/commit remains preserved. No schema or upstream app changes.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
No new progress percentage, U03 permission, real user data, external sender,
production deployment or real public publishing is claimed.

## Functions

- Anonymous-looking, **loopback-only** Arabic RTL preview of independently approved
  experimental publication editions explicitly allowed by temporary server policy.
- Search approved title/category/body and separately permitted reference metadata
  using existing Arabic normalization. Category facets are the actual editorial
  category strings of currently available editions; no invented fiqh taxonomy.
- Filter publications with an available reference, paginate 12 results, navigate
  publication → exact book/edition/printed part/page/hierarchy → publication/results.
  Query/category/material/page survive native-link navigation and return.
- Reuse current approved knowledge relationships to references. An approved private
  lesson/transcript relation gets a generic restricted-material notice only: no
  transcript ID/name/text/time range, raw evidence, case reference, staff URL or
  private source link. This surface never invokes the private transcript resolver.
- Show version number, independent publication approval date and current/superseded/
  withdrawn status for **explicitly allowed, previously approved editions only**.
  Historical bodies, titles, editorial reasons, identities and candidates remain
  excluded. Corrected versions require new independent approval and a new exact
  preview grant. Withdrawing the latest approved edition never reveals an older one.
- No mutation endpoint, alternative answer store, publication engine, queue or
  staff/service identity for anonymous readers. All canonical data stays upstream.

## Integration contract — coordinator-owned work

1. Add `apps.library_preview` to the synthetic campaign `INSTALLED_APPS`.
   No new migrations. Existing `APP_DIRS=True` discovers local templates.
2. Include the **routes** module in the integrated URLconf:

   ```python
   path("library-preview/", include("apps.library_preview.routes"))
   ```

   `apps.library_preview.urls` is the standalone test composition and imports
   `config.campaign_urls`; do **not** include that standalone module from the shared
   campaign URLconf. The routes module has no shared configuration import cycle.
3. Replace `apps.casework_web.guard.CaseworkGuard` in the synthetic middleware list
   with `apps.library_preview.guard.PreviewCompositionGuard`. It delegates all paths
   outside `/library-preview/` to the unchanged original CaseworkGuard. The preview
   prefix enforces literal loopback host and peer, no forwarding headers, GET/HEAD
   only, bounded query, no-store/noindex and restrictive CSP. Views independently
   repeat the boundary to protect inclusion without this middleware.
   If the integrator composes another outer guard, preserve these exact boundaries;
   never simply exempt this prefix from all guarding.
4. Keep these defaults:

   ```python
   FATWA_LIBRARY_PREVIEW_ENABLED = False
   FATWA_LIBRARY_PREVIEW_POLICY = None
   ```

   Existing publication/citation/knowledge flags must also be true for an explicitly
   configured synthetic demonstration. `FATWA_PRODUCTION` must be exactly `0`.
5. For a fixed synthetic demo/test, configure the frozen policy **in server code**:

   ```python
   from datetime import timedelta
   from django.utils import timezone
   from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant

   FATWA_LIBRARY_PREVIEW_POLICY = PreviewPolicy(
       publications=(PublicationGrant(approved_edition_uuid, approved_content_sha256),),
       references=(ReferenceGrant(reference_edition_id, source_row_id, source_sha256),),
       valid_until=timezone.now() + timedelta(minutes=30),
       synthetic_fixtures_only=True,
   )
   ```

   IDs and hashes must be taken from the actual human-approved synthetic fixtures.
   This example does not grant access by itself. Policy does not substitute for
   canonical approval: candidates, mismatched fingerprints, stale evidence, withdrawn
   or superseded versions still fail. Reference grants authorize **TOC metadata
   only**, not full text or private transcript material. There is no wildcard grant,
   HTTP policy editor, cookie-based policy, inferred rights or production fallback.
   Expiration must be within one hour; replacement/removal is checked on every read.
6. Add a development navigation link to `reverse('library_preview:index')` from the
   combined interface. No authenticated staff session is required by this preview;
   private workflows retain their original authentication. Do not add transcript,
   raw-origin or private-media URLs to the library templates.

Reusable services: `browse(query='', category='', material='', page=1)`,
`read(publication_id)`, `read_reference(publication_id, position)`.
The reference position is the canonical publication citation ordinal (1–12), not
an arbitrary catalog ID. Public service dictionaries are intentional allowlists;
never substitute `knowledge_links.history/browse` or publication model serialization.
Public GET filters are `q`, `category`, `material` (empty or `reference`) and `page`.
Unknown or repeated fields, credentials/return URLs and out-of-bound values fail.

## Safety and consistency

The policy pins at most 64 exact publication snapshots and 768 explicit reference
positions. Each read first checks the owned synthetic PostgreSQL database. It then
locks the canonical case and reuses `casework._verify`, publication approval/content/
citation validators, exact reference resolution and knowledge snapshot hashing.
Catalog reads acquire selected case locks in deterministic order; publication
withdrawal/correction uses the same locks. No ungranted case is included in the
catalog query or public projection. Case internals used for integrity validation
are never returned, logged or indexed by this app.

The adapter intentionally calls internal *locked read* validators because upstream
staff APIs require a real scoped MUFTI and a pre-transaction guard. It never invents
a principal to call those APIs, bypasses a synthetic ownership check, or patches
upstream authorization. These internal read dependencies should be maintained with
the upstream applications during integration.

All responses are no-store/noindex/no-referrer. The browser receives no login,
capability or CSRF cookie from this surface. Text is template-escaped; CSS is local;
there is no JavaScript, remote asset, redirect parameter or provider API. A failed
material lookup uses the same generic unavailable response for foreign, missing,
stale, withheld and withdrawn IDs. Private material has no route here at all.

## Evidence and reproduction

- Python **3.13.5**, Django **5.2.18**, fresh owned **PostgreSQL17.12**.
- Focused service/HTTP/security group: **14 passed, 1 fixture-cleanup error** on
  first run; that single test was corrected and **1/1 passed**. All 15 test methods
  have passed; successful unaffected tests were not rerun. After extracting the reusable routes
  module, the affected HTTP navigation test was rerun: **1/1 PASS**.
- **1/1 Chromium154.0.8037.57 PASS** on PG17: anonymous 320/1280px RTL, keyboard
  focus, zero horizontal overflow on list/detail/reference, Arabic search/filter
  preservation, publication→reference→return, no cookies, withdrawal closes both
  publication and reference URLs with404. Zero page errors, external requests or
  requests to `/casework/`. Local sandbox was explicitly **False**.
- One actual synthetic catalog read (one publication/two knowledge relationships):
  **34 SQL queries, 0.0328s** in the focused test executor. This is a local sample,
  not a production throughput/latency claim. No mutation of canonical rows occurred.
- System check, migration-drift check, Ruff and whitespace checks are included in
  final delivery. No new database migration is needed.
- Historical failures preserved: test cleanup disabled the same override twice;
  corrected to stack a separate revocation override. First browser run passed both
  viewport journeys but failed when a synchronous fixture withdrawal was invoked
  inside Playwright's async context; fixed by running that canonical operation in a
  dedicated thread, without disabling Django's safety checks. Initial Ruff flagged
  a star-import suppression on the wrong line; corrected. No known failure remains.
- **NOT RUN here:** PG18, sandbox-enabled Chrome, full V10 combined journey,
  production data/source permissions or real public deployment. V8/V9 historical
  evidence is preserved and not relabeled as V10 acceptance.

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.library_preview.settings -- \
  python manage.py test apps.library_preview.tests

FATWA_TEST_BROWSER_NO_SANDBOX=1 \
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.library_preview.settings -- \
  python manage.py test apps.library_preview.browser_tests
```

The browser executor needs Playwright1.58.0 and Chromium; shared dependencies were
not modified. The helper owns/removes its fresh cluster. Browser result artifact:
`.local/qa/library-preview/browser.json` (no private payloads).

## Limits retained

Book622 is one book's fiqh TOC, not a complete fatwa taxonomy or source text.
No real lesson model, licensed recording or authorized public transcript edition is
available from the existing contracts. Such materials remain private placeholders;
there is no claim of public lesson playback or full transcript navigation. A future
public transcript projection needs its own explicit rights/redaction/approval policy.

The preview policy is an expiring, manually configured development allowlist, not
production access-control governance or proof of real-content rights. Unknown
materials stay closed. The page history describes approved version chronology,
not a textual diff or permission to reopen old text. The bounded per-case reads are
not a large-corpus search index. Shared routing, middleware composition, navigation,
fixed demo grants and the final connected PG17/18 journey remain integration work.
