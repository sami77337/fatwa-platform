# S2 local implementation and actual test evidence

Date: 2026-10-13. Issue #3.
**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD.**
Gate B NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED; U03/U10 OWNER_APPROVAL_PENDING.

## Branch, inputs and scope

Checked-out branch: `codex/s2-rtl-public-fixtures-20261013`.
Actual Git HEAD before and after implementation:
`08f9e25e8ada9af56561d815f74b2c7ec9ba7ead`.
The working tree was clean before this work. All implementation, tests, logs and docs are local and uncommitted in `ui_drafts/fiqh/**` or `docs/ui-api-contract/**`.

Read `AGENTS.md`, `docs/coordination/PARALLEL_EXECUTION_20261013.md` and `_codex_input/queued_issue_3.md`. The current user's instruction to leave local changes overrides the issue/runbook delivery instructions about commits and PRs. No staging, commit, push, PR, merge, deployment, other-lane edit, secret access, source archive script execution, or legacy Telegram bot change was performed.

Default tested input fixture: `s2-synthetic-11397-v1`.
Actual deterministic SHA256 of UTF-8 `JSON.stringify(createFixture().nodes)`:

```text
4d334f7d4be2966a5125c720a5c1ed8d20e0f0ac84a687b7df46aade1eadfb33
```

The fixture has 11,397 unique synthetic heading nodes, 32 roots (30 books plus two introductions), maximum depth five. Every title and citation is test metadata.

The owner source ZIP was actually supplied locally:
`_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip`, 3,216,947 bytes.
Actual SHA256 matched the owner-provided expected identity:

```text
82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce
```

The source-identity test passed. This verifies the archive bytes only. Real headings, full TOC edges, source counts, importer acceptance and source-backed UI acceptance were not tested. No real heading data was copied into the demo.

## Actual final results

Environment: Windows PowerShell workspace; Node `v24.16.0`.

| Check | Actual result |
| --- | --- |
| Node fixture / API / preview negatives / source identity | PASS: 19 tests, 0 failures, 0 skipped, exit 0 |
| Syntax checks for all 8 JavaScript/module files | PASS: all `node --check` exit 0 |
| Browser acceptance command | FAILED at initialization: exit 1, `CDP timeout: Page.enable` |
| Browser DOM/keyboard/ARIA/mobile assertions | NOT_RUN: zero UI checks completed |
| Desktop/mobile screenshots and visual QA | NOT_RUN: page initialization unavailable, no screenshots produced |
| Managed browser fallback | Unavailable: inventory had no browsers; in-app browser creation reported `Browser is not available: iab` |
| Django/system/migrations/PostgreSQL acceptance | NOT_RUN: no S0 backend is present in this checkout; outside S2 scope |
| Real-source browser / screen-reader / physical-device acceptance | NOT_RUN |
| CI | NOT_RUN: no workflows changed or triggered |

Actual final passing command:

```powershell
node --test ui_drafts/fiqh/tests/api.test.mjs ui_drafts/fiqh/tests/server.test.mjs ui_drafts/fiqh/tests/source-identity.test.mjs
```

Actual final output excerpt:

```text
✔ supplied book-622 ZIP matches expected SHA256 (identity only, no source-heading acceptance) (4.9716ms)
ℹ tests 19
ℹ suites 0
ℹ pass 19
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 413.6364
```

Full output: [node-tests.txt](../../ui_drafts/fiqh/artifacts/node-tests.txt).
Syntax evidence: [syntax-results.json](../../ui_drafts/fiqh/artifacts/syntax-results.json).

Passing tests cover hierarchy integrity and counts, 20-item sibling/search pages, reversible cursors, anchored reveal, depth-five breadcrumb edges, Arabic normalization without changing original titles, invalid/empty-normalized queries, literal search, missing IDs, cancellation, response isolation, private-field projection, rejection of fatwa kinds, source/edition drift, root/leaf invariants, source ordering, same-origin GET-only requests with omitted credentials, malformed/oversized payload rejection, and HTTP 405/404 preview negatives. They do not substitute for browser or backend acceptance.

Browser command:

```powershell
node ui_drafts/fiqh/tests/browser.mjs
```

Chrome `154.0.8037.98` reported its version through DevTools, but `Page.enable` timed out before any page interaction. Edge `155.0.4283.45` had the same page initialization timeout. An initial default Chrome attempt also reported GPU subprocess failures. Restricted-process variants were tried during diagnosis; none completed UI checks. The final checked-in runner retains browser sandboxing, uses a disposable profile and `--in-process-gpu`, and has no fallback that disables sandboxing.

An initial browser-harness string quoting syntax error was corrected; final syntax checks pass. The environment's normal shell tool also failed before launch with `helper_unknown_error: setup refresh had errors`; read-only Git and Node commands subsequently ran using the available Node child-process facility.

Full final browser failure: [browser-run.txt](../../ui_drafts/fiqh/artifacts/browser-run.txt).
Machine-readable status: [browser-results.json](../../ui_drafts/fiqh/artifacts/browser-results.json).
Temporary profiles were removed after each attempt; the temporary preview process was stopped.

## Exact repeatable manual browser plan

This plan is included because this environment could not execute browser acceptance. None of the expected observations below are claimed as observed passes.

1. Run `node ui_drafts/fiqh/server.mjs` from the repository root; open `http://127.0.0.1:4173/` in a current desktop browser. Confirm Arabic text, RTL direction, synthetic warning, 30 book buttons, two introduction buttons, and no fatwa actions.
2. Wait for loading to finish. In developer tools, inspect `document.querySelectorAll('[role="treeitem"]').length`: expected 21 (one chosen book plus 20 direct children), rather than 11,397. Confirm exactly one visible treeitem has `tabindex="0"`.
3. Tab to the tree. Right should collapse the root to one treeitem; Left should expand it again. Down/Up should move through visible nodes; Home/End should move to first/last visible node. Enter and Space should toggle a branch; Tab should leave the tree. Check that the focused treeitem shows a visible outline.
4. Expand a depth-two node, then a depth-three node, then depth four. Select a leaf. Confirm five-level breadcrumbs, a reference-heading badge, source/edition/madhhab, and labelled synthetic printed part/page. A leaf must omit `aria-expanded`.
5. Expand another sibling at depth two. The previous sibling's descendants should leave the DOM. Treeitem count must remain at most 81, with one Tab stop. Inspect `aria-level`, `aria-posinset`, `aria-setsize`, `aria-expanded` and `aria-selected`.
6. Return to the first book. Click the next child-page control. Expected four children with source sibling positions 21–24, not 20 appended children. Click previous. Focus should return to the parent treeitem, and the first 20 children should replace that page.
7. Search for `كِتَاب`. Confirm at most 20 result rows and source/edition/madhhab/part/page for each. Next and previous search pages must replace rows. A result pagination action should focus the results heading.
8. Select the first book in the search scope and search for `باب تجريبي ٢٤`. Expected one result. Open it: its sibling page should show positions 21–24, the exact heading should receive focus, and the breadcrumb must include the book and heading. Click the ancestor breadcrumb and confirm tree focus moves to the book.
9. Search for `لايوجدعنوانمطابقلهذهالعبارة`: expected an Arabic no-results message. Search for one letter or only Arabic vowel marks: expected an Arabic validation error and `aria-invalid="true"`. Clear should remove results/error state and focus the query field.
10. Select an introduction. It should appear as a single leaf without expanded state. Switch quickly among books and introductions while data is loading. A late request must not restore an older root.
11. For a deterministic child-loading failure, run the following only in the local synthetic demo's developer console:

```javascript
const m = await import("./app.js");
const savedChildren = m.mockAdapter.children;
m.mockAdapter.children = () => Promise.reject(new Error("synthetic failure"));
```

Click a book. Expect an Arabic failure/retry control, cleared busy state and usable navigation. Restore with `m.mockAdapter.children = savedChildren`, then click retry; expect successful lazy loading with the original parent.

12. For a search failure, similarly save `m.mockAdapter.search`, replace it with a rejecting function, submit `كتاب`, restore it, then retry. Expect the original query and scope to be retained.
13. Rapidly submit two queries, then clear a pending search. Results of an older or cleared request must never replace the newer state. The automated browser harness includes a transport that deliberately ignores abort to make this repeatable.
14. At desktop width, confirm no horizontal page overflow and readable navigation/tree. At 390×844 and 320×720 viewport sizes, confirm no horizontal overflow, wrapping controls/titles, vertically scrollable book navigation, controls at least 44 CSS pixels high, and usable tree keyboard behavior.
15. Inspect the browser accessibility tree and test with an Arabic-capable screen reader. Confirm the labelled tree/search/navigation, selected/expanded states, source distinctions, live loading/error/empty announcements, and breadcrumb labels. This requires independent human acceptance.
16. Inspect the network panel. The default mock should request only local static kit assets, with no external catalog/AI/CDN/private-data requests. The preview should return 405 to POST/PUT/PATCH/DELETE and 404 to repository/private-product paths.
17. Stop the local server. The intended automated equivalent is `node ui_drafts/fiqh/tests/browser.mjs`; rerun it in a browser-capable environment and review generated screenshots before claiming UI acceptance.

## Handoff and remaining blockers

S0 receives [the proposed endpoint contract](REFERENCE_READ_API.md), not backend changes. The mock is the only default runtime adapter. Source-pinned production wording, real-source mapping, reviewed backend GET endpoints, PostgreSQL evidence and successful browser/screen-reader checks must precede integration acceptance.

The Node checks passed. Browser rendering/keyboard/ARIA/mobile acceptance remains blocked by the available runtime. Full real-source TOC acceptance, backend integration and policy acceptance remain pending. No gates were advanced.
