# S2 Arabic RTL fiqh interaction kit

Local implementation for issue #3 on `codex/s2-rtl-public-fixtures-20261013`.
**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD.**
Gate B NOT_PASSED, Gates C/D/E HOLD, Phase01 BLOCKED. U03/U10 owner approval remains pending.

This is plain static HTML/CSS/JavaScript with no build step, remote CDN, package install, account, AI integration, or private data. All visible labels are Arabic. Styling is temporary; final branding and Figma remain deferred.

## Run locally

From the repository root, using Node 22 or newer (tested here on Node 24.16.0):

```powershell
node ui_drafts/fiqh/server.mjs
```

Open `http://127.0.0.1:4173/`. Stop the server with Ctrl+C.
To choose another port, set the optional `FIQH_PREVIEW_PORT` environment variable.

The server binds only to loopback, serves an explicit list of kit assets, rejects POST/PUT/PATCH/DELETE with 405, and does not serve test files, source ZIPs, or repository files. No product API is created. Use HTTP rather than opening `index.html` directly; browser ES module rules may reject `file:` imports.

## Functions

- Separate navigation for 30 books and two introductions.
- Lazy loading of 20 children per request, with previous/next pages.
- Pointer and keyboard expansion/collapse with a single expanded sibling branch at each depth.
- An ARIA tree with one Tab stop, level/position/set size, expanded and selected states.
- Arabic RTL keyboard directions: Left opens/moves to a child; Right closes/moves to a parent. Up/Down, Home/End, Enter, and Space are supported. Tab leaves the tree.
- Breadcrumb navigation and public heading metadata, with source, edition, madhhab, printed part and page.
- Bounded Arabic title search, optional book/introduction scope, result paging, and opening an exact result path even when its sibling is beyond page one.
- Loading, empty, failure, retry, cancellation, and stale-response handling.
- A responsive layout intended for desktop and narrow mobile viewports.

The tree mounts at most **81 treeitems**: one chosen root plus up to 20 siblings at each of four descendant levels. Search mounts at most 20 result rows. Pages replace siblings instead of accumulating them. This is a design bound guarded in code; browser verification was blocked in this environment.

## Fixture and source identity

The default adapter generates `s2-synthetic-11397-v1`: 11,397 unique synthetic title nodes, 32 roots (30 books and two introductions), maximum depth five. Every title and printed citation is invented test metadata, explicitly labelled as synthetic and as a reference heading rather than a fatwa. These counts exercise catalog scale and do not imply acceptance of the real source.

The owner archive was supplied in this workspace at
`_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip`.
Its actual SHA256 was verified as:

```text
82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce
```

Only the archive identity and entry metadata were inspected. No scripts inside the archive were run, no full book text or real headings were copied into this UI, and no ingest or real-heading acceptance is claimed. The optional archive-identity test skips explicitly if the archive is absent in another checkout.

## Tests

Run from the repository root:

```powershell
node --test ui_drafts/fiqh/tests/api.test.mjs ui_drafts/fiqh/tests/server.test.mjs ui_drafts/fiqh/tests/source-identity.test.mjs
node ui_drafts/fiqh/tests/browser.mjs
```

The first command verifies fixture hierarchy, API paging/search/error/cancellation boundaries, public metadata projection, read-only request behavior, bounded response parsing, preview HTTP negatives, and the optional supplied ZIP identity.

The browser runner needs an installed Chrome/Chromium (Edge fallback), uses Node's built-in WebSocket/CDP support, starts an ephemeral loopback server, and creates a fresh disposable headless profile within this lane. Set `FIQH_BROWSER_PATH` to an existing browser executable if needed. It does not reuse personal profiles. The final runner keeps browser sandboxing enabled and uses `--in-process-gpu`; it writes results and screenshots to `artifacts/` and validates the profile path before cleanup.

Browser tests cover DOM/keyboard/ARIA, paging, deep expansion, source badges, breadcrumbs, error/retry, stale results, literal HTML rendering, desktop and 390/320-pixel layouts, and absence of external or mutating kit requests. See [test evidence and manual plan](../../docs/ui-api-contract/S2_TEST_EVIDENCE.md) for actual outcomes. A harness failure before page initialization is **NOT_RUN** for those UI assertions, not a pass.

## Integration handoff

The UI defaults exclusively to the mock adapter. The separate `createReadOnlyAdapter` is unit tested and documented in [the proposed API contract](../../docs/ui-api-contract/REFERENCE_READ_API.md). It requires same-origin GET endpoints and projects only heading metadata. Its methods are `catalog`, `children`, `node`, and `search`.

S0 owns Django routes/templates/models/settings; this lane does not wire or modify them. Before any integration, S0 must implement and review the proposed contract, source verification and authorization boundaries must be accepted, the synthetic notice must be replaced with source-aware wording, and UI acceptance must run against the reviewed source and backend. The standalone HTML remains synthetic by default even if a developer mounts another adapter in a test.

Not implemented: production integration, Django/PostgreSQL acceptance, verified real-source browsing, screen-reader/device acceptance, fatwa publishing, requester/user operations, permissions, other scientific taxonomies, AI, and final visual design. No Git commit, push, PR, merge or deployment was performed for this work.
