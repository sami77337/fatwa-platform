# S0 read-only backend integration contract

Base for development: http://127.0.0.1:8000. Paths use **no trailing slash**;
APPEND_SLASH is false. Only GET and HEAD are allowed. Every other method,
including OPTIONS/TRACE and methods at unknown product paths, gets 405 with
Allow: GET, HEAD before database work. No CORS/provider integration is enabled.
Missing GET/HEAD routes get 404; invalid inputs 400; unavailable DB/schema 503.
Database exception details are not returned.

| Endpoint | Behavior |
|---|---|
| / and /fiqh | SSR catalog/edition chooser/search |
| /fiqh/nodes/{source_row_id} | Heading citation, breadcrumbs and bounded child list |
| /fiqh/nodes/{source_row_id}/children | htmx HTML child fragment; full heading page without HX-Request |
| /api/v1/fiqh/books | Paginated public work+edition inventory |
| /api/v1/fiqh/roots | Paginated roots in the selected edition |
| /api/v1/fiqh/nodes/{source_row_id} | Single heading plus root-to-self ancestors |
| /api/v1/fiqh/nodes/{source_row_id}/children | Paginated direct children, source sibling order |
| /api/v1/fiqh/search | Bounded title search in one edition |
| /api/v1/status | Public inventory/read-only state; no acceptance assertion |
| /healthz | Process liveness, without a database probe |
| /readyz | Schema/database reachability, without a gate pass |

edition is the ORM edition ID returned in books. If omitted, the API selects
only when exactly one edition exists; multiple editions produce 400. An empty
catalog returns empty roots/search/books; unknown edition/node gets 404. Source
row IDs and parent IDs always refer to source IDs within that edition, not
internal heading PKs. Ancestors include the current node and are bounded at 5.

## Query limits and payload

Pagination: limit=30 default, 1..100; offset=0 default, 0..20000. No unbounded
pagination. Numbers must use ASCII decimal digits. Unknown/repeated parameters
are rejected. Raw query strings above 4096 characters get 400; paths above 2048
characters get 414. Node/source IDs and edition IDs are bounded to positive
PostgreSQL bigint range. Search: q length <=160, <=10 terms, no control chars.

mode=normalized is default. It normalizes NFKC, alif variants, alif maqsura,
diacritics, tatweel, case and whitespace only for search; it does not merge
ha/ta-marbuta, invent synonyms or rewrite original titles. mode=literal matches
all whitespace-separated original-text substrings. mode=exact matches the whole
original title including its spelling/spacing. Literal LIKE metacharacters are
escaped by Django's ORM, and values are bound parameters. Empty API search is
empty; an empty HTML search shows roots for convenient browsing.

Every catalog JSON response carries kind=SOURCE_BOOK_TOC_NOT_FATWAS. Lists have
items, total, count (same total), limit, offset, next_offset. Search additionally
has query/mode. Root/child/node/search responses include an explicit edition
object. A heading exposes only:

~~~json
{
  "id": 1, "source_id": "synthetic-1", "parent_id": null,
  "title": "عنوان اصطناعي", "depth": 1, "position": 1, "source_order": 1,
  "children_count": 2, "part": "مقدمة", "page": 1, "page_id": 11,
  "source_entry_number": null
}
~~~

This example is synthetic. Edition objects expose title/publisher, source hashes,
counts and a work containing source namespace/book ID, original title and madhhab.
They do not expose input filesystem names, ingest internals or arbitrary model
fields. No case, requester, account or approved-ruling table exists in this app.

All responses get no-store, CSP with local scripts/styles only and no inline
or eval permission, nosniff, frame denial and no-referrer. Cached fragments and
private content mixing are avoided; HX-Request varies HTML response shape.
The local asset view restricts paths to S0 CSS/JS and installed django-htmx JS;
it does not serve archive contents or arbitrary filesystem paths.

S2 should retain native summary/details expansion and no-JS links, labelled GET
search, real source citation, RTL and visible keyboard focus. SSR currently shows
at most 100 editions in the chooser; this sprint has one reference work. Use the
paginated books API for any future larger inventory. S2 integration/browser QA,
S4 independent HTTP QA and S5 CI are pending; this document asserts no UI pass.
