# S4 proposed public source catalog contract

Issue #5 owns this independent integration proposal. S0 has supplied no backend or
API contract in this checkout. These paths, field names, limits and error shapes
must be reconciled with S0 after integration; they are not implemented product
endpoints, accepted owner policy or an approved global fatwa taxonomy.

The executable TypeScript types and validators are in [catalog.ts](catalog.ts).
The profile is [proposed-profile.json](proposed-profile.json), and the fixture is
[synthetic-catalog.json](synthetic-catalog.json). They have no dependencies beyond
Node.js 24.16.0 (tested here). Node executes erasable TypeScript syntax; it does **not**
perform static type checking. Both JSON inputs undergo runtime validation.

## Synthetic fixture identity

Identity: **s4-public-catalog-synthetic-v1**. Four fabricated public titles: two
roots and two children, including a deliberate HTML payload treated as literal
title text. All public titles contain the positive selector **اختبار**; **فرع**
selects the two children. Public ordering is ascending order, then identifier.

Three private canaries represent a fabricated requester artifact, unapproved
fatwa and user contact. Their values are synthetic, not credentials or real user
data. A private lookup selector and hidden identifier are distinct from the
canaries: the harness sends selectors, never private marker values. The integrated
disposable target must actually contain the synthetic private canaries in isolated
private test fixtures before the privacy probes have evidential value. This lane
provides no Django seed command or private product models.

The source metadata explicitly identifies a **synthetic, unverified** edition of
reference 622, Hanbali school, and source_table_of_contents. No book text, original
ZIP or verified edition content is included. Stable equality of this synthetic
metadata is the oracle; this cannot validate the original 11,397-title corpus.

## Proposed routes

| Profile key | Default route | GET body |
|---|---|---|
| roots | /api/reference/roots/ | Paginated public roots |
| node | /api/reference/nodes/{id}/ | Exactly one public node |
| children | /api/reference/nodes/{id}/children/ | Paginated direct children |
| search | /api/reference/search/ | Paginated literal title matches |
| web | /reference/ | Arabic RTL reference browsing HTML |
| web_search | /reference/search/ | Arabic RTL search HTML |

Successful public GET and HEAD return 200. HEAD has an empty body. Public
POST/PUT/PATCH/DELETE return **405**, with Allow containing GET and HEAD and no
mutating method. Optional OPTIONS may appear in Allow; the harness does not
require an OPTIONS endpoint. A 403 alone is insufficient on public read routes:
it might hide an active write route behind CSRF middleware.

Forbidden probes cover fatwas, publishing, requesters, users, permission grants,
workflow transitions, AI fatwas, delivery and admin. GET and each mutating method
must return a configured subset of **403/404/405**, with no redirect or public
state change. Forged role headers never authorize these requests.

## Exact public JSON schemas

A page has exactly count, next, previous and results. count is an integer equal to
the seeded public result count. next and previous are null or same-origin URLs
for the same collection with exactly q (for search), page and page_size. Links
must advance/retreat by one page, preserve the size and query, and carry no
credentials, fragments, duplicate parameters or unrelated fields.

A node has exactly id, parent_id, title, order, printed_part, printed_page,
has_children and source. Every value must equal the seeded public node. No
requester fields, user fields, private cases, unapproved fatwa data or additional
metadata can enter the public schema unnoticed.

source has exactly book_id, work_title, edition, school, catalog_kind and
fixture_id. Each response must preserve the complete source object.

JSON errors have exactly error, with exactly code and message. code is uppercase
ASCII letters/underscores (1–64 characters); message is a string of at most 256
characters. HTML errors may be bounded framework error pages, with the required
headers, no known private marker and no detected backend traceback/SQL diagnostics.

## Limits and escaping

The default profile sets page_size to at most 2 and q to at most 64 Unicode UTF-16
code units. (The overlength boundary uses Arabic BMP characters, whose length
matches Python code-point counting.) Page and size must be positive decimal
integers. Duplicate q/page/page_size, empty/blank q and an overlength q return 400.
An out-of-range page returns 400 or 404. The exact maximum query length is accepted.

SQL payloads within the limit are literal queries yielding the seeded literal
matches, normally an empty page. The XSS payload matches the seeded title: JSON
preserves that string with application/json and nosniff; HTML displays escaped
text. Web search rejects unsafe next destinations with 400 and no Location.

Public responses and rejected probes require nosniff, same-origin or no-referrer
Referrer-Policy and Cache-Control: no-store. The no-store requirement is deliberately
strict for this synthetic privacy run. Any future public caching contract requires
an explicit S4 review with isolation tests; it must not be silently relaxed.

HTML additionally requires text/html, Arabic lang and RTL dir on the html element,
X-Frame-Options DENY or SAMEORIGIN, and the restrictive CSP detailed in the
[acceptance oracle](../../docs/security-review/ACCEPTANCE_ORACLE.md).

## Handoff boundary

S0 owns all Django implementation, root Python dependencies and database fixtures.
S4 owns this contract and harness. Route names and integer limits are configurable
in the profile. Response-field changes require updating the explicit S4 schema and
oracles after a reviewed contract agreement. Never weaken an oracle simply to
convert a failing target into a pass. Root CI changes belong to S5.
