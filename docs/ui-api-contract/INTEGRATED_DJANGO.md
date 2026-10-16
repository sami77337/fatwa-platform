# Integrated Django read contract

This worktree uses the actual S0 endpoints below. The original S2 proposal and
standalone fixture remain in ui_drafts/fiqh for provenance/regression tests only.
Django never serves fixture.js, api.js, or the standalone index.html.

| S2 operation | Actual Django GET endpoint | Mapping |
| --- | --- | --- |
| catalog | /api/v1/fiqh/books then /api/v1/fiqh/roots?edition=ID | Edition inventory and original roots; classify the two introductions only for the pinned book-622 archive. |
| children | /api/v1/fiqh/nodes/ID/children?edition=ID&limit=20&offset=N | next_offset becomes the S2 numeric cursor string; previous cursor is derived from offset/limit. |
| anchored children | Same children URL with anchor=SOURCE_ROW_ID | Server counts preceding siblings and selects the containing page, including non-contiguous original positions. anchor and offset together return 400. |
| node | /api/v1/fiqh/nodes/ID?edition=ID | ancestors includes the selected node and maps to S2 breadcrumbs. |
| search | /api/v1/fiqh/search?edition=ID&q=TEXT&mode=MODE&root=ROOT_ID&limit=20&offset=N | Optional root scope uses at most four parent joins. Modes remain normalized/literal/exact. |

IDs in URLs are original numeric source row IDs, not Django primary keys. The
original lucene_title_key is retained separately as source_id. Original printed
part is a string and can be المقدمة; page_id is distinct from the printed page.
Original titles are rendered using textContent in the S2 view and Django's default
escaping in SSR. The client drops unknown row fields.

Every request uses same-origin GET, credentials=omit, cache=no-store, redirect=error,
and an abort/timeout signal. Every payload must carry S0's
SOURCE_BOOK_TOC_NOT_FATWAS marker and the selected edition/source hashes. No fixture
fallback exists. Empty/unavailable databases remain empty/unavailable.

The Django page initially renders the S0 server catalog. The S2 interface appears
only after the catalog API succeeds. Use ?basic=1 for the server-rendered form,
search, breadcrumbs and paging, or disable JavaScript. Explicit server form
searches and nonzero offsets keep their SSR results. The interactive edition
chooser uses a normal GET; selected headings have edition-pinned shareable links.

The existing GET/HEAD-only middleware, CSP, source projection and immutable
PostgreSQL migrations are retained. No privileged routes or schema changes were
introduced. Root and anchor are the only API parameter additions.
