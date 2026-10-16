# A1 — Arabic reference catalog functions

2026-10-15. NOT_DEPLOYED / GATES_HOLD. Base HEAD:
d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe.
The lane began with existing uncommitted integration files. A1 changes are
measured against initial file hashes, not a clean upstream checkout. No commit,
push, PR, merge, site mount change, Docker action, import or database write was
performed. These edits remain in A1 for scope review.

Native links now serve roots, breadcrumb ancestors and search results. Direct
heading links reveal the real ancestor path, select the target and load children
for a branch. Every open ancestor retains its bounded sibling pager. Browser
history stores tree pages, selection and search state; back/forward aborts
pending navigation and restores the snapshot. Arrow keys move one tree tab
stop; RTL left opens/enters, right closes/returns to the parent, Home/End move
within visible nodes and Enter/Space select and toggle. Focus movement alone
does not add history entries.

Loading, empty, unavailable, invalid-query and missing-heading paths have Arabic
messages and recovery. Failed interactive startup leaves SSR visible with retry.
Search paging retains the submitted scope and mode. Stale responses are ignored
even when transport ignores abort. Original title text uses textContent; Django
autoescaping remains enabled in SSR.

Edition selection and visible source/page IDs are removed. A concise notice says
these are headings from one Hanbali reference, not published fatwas or the global
taxonomy. Edition, publisher, printed part and printed page remain in scholarly
citations. The edition stays internally pinned in requests, links and hidden
form data. No invented headings, fatwa answers or fallback data entered the site.

## Files changed within ownership

- templates/reference/base.html: concise notice and footer.
- templates/reference/catalog_content.html: SSR search, root/breadcrumb links,
  citation and empty states without edition controls or internal metadata.
- templates/reference/heading_list.html: printed references, child/empty labels;
  direct heading links and SSR paging remain intact.
- templates/reference/interactive.html: root/basic navigation, search scope,
  keyboard guidance and named branch-pagination landmark.
- templates/reference/error.html: public error and recovery link.
- apps/reference/static/reference/catalog.js: navigation/history, focus,
  reveal, ancestor paging and asynchronous state handling.
- apps/reference/static/reference/django-api.mjs: ordinal mapping and stronger
  checks of the selected source's scholarly attribution.
- apps/reference/static/reference/catalog.css: native-link targets, focus,
  selection, paging and narrow-width rules.
- apps/reference/static/reference/tree.js: SSR/htmx busy/error announcements.
- tests/integration/ui/**: isolated Node, SSR, live and browser verification.
- docs/dev/a1/**: notes and actual verification evidence.

## Actual verification

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Integrated UI/adapter/SSR-event Node regressions | PASS | 31 passed, 0 failed: 20 new A1 tests and 11 existing adapter tests. DOM harness tests actual handlers; it has no layout or accessibility engine. |
| All available Node regression files | PASS | 54 passed, 0 failed, 2 skipped of 56. [Raw output](node-tests.txt). Historical standalone kit tests use synthetic fixtures/mock transport and do not establish real-source acceptance. |
| Original archive and real live API sample | PASS | Six checks in [live-result.json](live-result.json). ZIP and JSONL rehashed, all 32 root IDs matched input, metadata 11,397/32/5 confirmed, sampled depth-five path/citations matched, anchored paging/search/HEAD/405 rejection checked. This is sampled HTTP acceptance, not a new exhaustive comparison of every live record or SQL testing. |
| JavaScript module syntax | PASS | Nine files checked using node --input-type=module --check with file bytes on stdin; [checks.json](checks.json). |
| Whitespace and ownership | PASS | git diff --check; [hash-based scope audit](scope-audit.json). Git emitted CRLF normalization warnings only. |
| Browser / actual keyboard / AX / mobile rendering | NOT_RUN | Chrome 155 launched, but Page.enable timed out before initialization; zero UI checks completed. GPU access/process errors are in [browser-result.json](browser-result.json). No screenshot or visual pass is claimed. |
| Django SSR template tests | NOT_RUN | py --list-paths reported “No installed Pythons found!”. Four database-free SimpleTestCase checks added; no Python installation or Docker changes attempted. |
| PostgreSQL/Django integration suite | NOT_RUN | No test database created, seeded or reset. Live verification used the existing HTTP API. |

The two skipped historical archive checks resolve old fixture locations absent
from this worktree. The separate A1 command used the actual original archive
path and passed both pinned SHA256 checks.

Original ZIP: FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip.
Archive SHA256:
82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce.
JSONL member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl.
JSONL SHA256:
37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14.
Real sample: 8550 → 8551 → 8665 → 8667 → 8668,
“النوع الثاني: تفويض المهر”. The anchored path includes a sibling beyond the
first page. A1 did not revalidate the original-title CSV or upstream DB archives.

The server on port 8000 continues serving the owner's integration files;
a1_assets_on_existing_site: false was measured. These UI/SSR edits need later
cross-lane integration to appear there. Live API checks are not browser
acceptance of the unserved A1 templates.

## Reproduction commands

Integrated UI checks without a database:

~~~powershell
node --test tests/integration/django-api.test.mjs tests/integration/ui/adapter.test.mjs tests/integration/ui/catalog.test.mjs tests/integration/ui/tree.test.mjs
~~~

All available Node regressions (old optional source locations can skip):

~~~powershell
node --test tests/integration/django-api.test.mjs tests/integration/ui/adapter.test.mjs tests/integration/ui/catalog.test.mjs tests/integration/ui/tree.test.mjs tests/dev/host.test.mjs ui_drafts/fiqh/tests/api.test.mjs ui_drafts/fiqh/tests/server.test.mjs ui_drafts/fiqh/tests/source-identity.test.mjs
~~~

Real-source acceptance with explicit original ZIP path:

~~~powershell
node tests/integration/ui/live.mjs http://127.0.0.1:8000 "C:/Users/Abu AL-yazeed/fatwa-codex-parallel/inputs/starter/FATWA_CODEX_START_20261013/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip" docs/dev/a1/live-result.json
~~~

Browser checks when a functioning renderer is available:

~~~powershell
node tests/integration/ui/browser.mjs http://127.0.0.1:8000
~~~

The browser runner creates a temporary loopback overlay from A1's interactive
template and actual assets, forwarding GET API reads to the existing catalog.
It does not replace the live site or render Django SSR. A temporary browser
profile inside A1 docs is checked and removed after shutdown. An optional
second argument selects a Chrome/Edge executable. Zero UI checks completed here.

With installed project Python/Django dependencies, database-free SSR checks:

~~~powershell
python -B manage.py test tests.integration.ui.test_templates --keepdb
~~~

## Notes for A2/A3 and integration review

Contract reviewed: apps/reference/views.py, services.py, query.py,
config/urls.py and docs/ui-api-contract/INTEGRATED_DJANGO.md. No backend edited.

1. Original sibling positions can have gaps. A1 preserves them, derives ARIA
   ordinal from offset + index + 1 and set size from total. The adapter exposes
   these distinct fields for rendering.
2. Anchored children require anchor without offset. Ancestors include the
   selected node. Direct reveal uses both documented behaviors.
3. Current HTML routing leaves multi-edition ambiguity unresolved. A1 presents
   a neutral unavailable state and no edition chooser. Default public-reference
   routing in that future scenario belongs to the backend lane.
4. Historical tests outside A1 still expect visible test-202 in
   tests/integration/test_site.py and “اختر الطبعة” in
   tests/reference/test_catalog.py. Those assertions conflict with the current
   owner instruction and need owner-lane adjustment during integration. They
   were neither executed nor changed by A1.
5. The API continues carrying pinned provenance. Only public UI presentation
   changes; stored source/edition attribution and scholarly citations remain.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; U03/U10 pending.
