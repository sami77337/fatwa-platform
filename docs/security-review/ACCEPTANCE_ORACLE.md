# S4 precise acceptance oracle

Scope: issue #5, public source catalog, synthetic development evidence only.
NOT_DEPLOYED / GATES_HOLD. The proposed routes and typed fixture are specified in
[the contract](../../quality/api_contract/README.md). The suite is implemented in
[suite.ts](../../quality/security/suite.ts); response oracles are in
[oracle.ts](../../quality/security/oracle.ts). No S0 backend contract is available
on this branch, so this is an integration proposal.

## Test prerequisites

Identify Git HEAD, branch, harness fingerprint, fixture identity, fixture SHA256
and profile SHA256. Use a resettable loopback-only server with exactly the four
fabricated public nodes and three isolated synthetic private canaries. S0 must
supply the seed/reset procedure and evidence that private canaries really exist.
The source edition labels are explicitly synthetic. Any unavailable input or
runtime dependency remains NOT_RUN, SERVER_NOT_AVAILABLE or INCOMPLETE.

The initial preflight traverses all pages of the positive اختبار search and
verifies the full public fixture. Failure stops subsequent probing. This prevents
universal 404/403 behavior from satisfying negative tests. No mutating request is
sent without the disposable synthetic target flag.

## HTTP, body and observable side effects

| Case family | Request and required status | Body and side-effect oracle |
|---|---|---|
| public-fixture-preflight | GET all positive search pages, 200 | Exact four public nodes, exact count, citations, parent edges, ordering and source object |
| public-roots-page-* | GET roots with page_size=1, 200 | Exact roots, one result per page, bounded same-origin next/previous links |
| public-node-* | GET each fixture node, 200 | Exact allowed fields and seeded values, stable source edition |
| public-children-* | GET each node's direct children, 200 | Exact two children for root A and empty collections for leaves/root B |
| public-search-positive | GET q=فرع, 200 | Exact two seeded children and public count=2 |
| public-search-idempotent | Repeat positive paginated search, 200 | Canonical JSON equality with baseline across all public nodes |
| public-head-* | HEAD each API surface, 200 | Empty body and required privacy/security headers |
| public-web-positive | GET reference HTML, 200 | Arabic RTL, source work/edition visible, Hanbali/reference labels and required headers |
| xss-literal-json | GET literal seeded payload, 200 | Exactly matching synthetic node; string preserved as JSON data |
| xss-escaped-web-* | GET web search with title/query payload, 200 | Escaped seeded title visible; no raw payload or executable canary markup |
| sql-literal-* | GET three SQL-like queries within limit, 200 | Empty literal-match pages, no SQL diagnostics and unchanged public snapshot |
| bounds-* | Invalid/duplicate q/page/page_size, 400 | Bounded public error; exact maximum q accepted with 200; missing page 400/404 |
| unsafe-redirect-* | Web search with absolute, scheme-relative, javascript or backslash next, 400 | No Location, no redirect followed, no private artifacts |
| private-search-and-repeat | GET private lookup twice, 200 | Both result/count sets empty; equal repeated responses and no canary in body/headers |
| private-node-not-public | GET hidden synthetic node ID, 404 | No private payload, diagnostics or redirect |
| forbidden-get-* | GET deferred/forbidden interfaces, 403/404/405 | No private payload, redirect or accepted business operation |
| readonly-* | POST/PUT/PATCH/DELETE each public surface, 405 | Allow includes GET/HEAD, permits only GET/HEAD/OPTIONS; full public snapshots before/after equal baseline |
| forbidden-* | Each mutating method against forbidden paths, 403/404/405 | Bounded error and full public snapshots before/after equal baseline |
| forged-role-* | POST forbidden route with four forged role headers, 403/404/405 | MUFTI, ORGANIZER_ADMIN, ORGANIZER and DOMAIN_TRANSACTION header claims confer no grant; snapshots unchanged |
| csrf-invalid-web-token | POST web search with a fabricated invalid token, 405 | Write operation stays unavailable; snapshots unchanged |
| final-public-state-unchanged | Repeat complete public search after all selected probes, 200 | Full public snapshot equals baseline, including when mutating probes are disabled |
| private-artifacts-in-local-log | Read current test-only log after all requests | Nonempty bounded log contains current run marker, has no decoded private canary; missing log remains NOT_RUN |

Every JSON page has exactly count/next/previous/results. Every node and source uses
an exact field allowlist and seeded value equality. JSON errors have exactly the
bounded error object. Unknown public fields fail even when no canary is present.
Privacy inspection covers response bodies and all returned header values, including
common JSON Unicode, numeric HTML entity and percent encodings of the synthetic
markers. Log inspection uses the same canary decoding. This is a known-canary
oracle, not a general personal-data classifier.

## Web/security acceptance

All exercised responses require X-Content-Type-Options: nosniff, restrictive
Referrer-Policy (same-origin or no-referrer), and Cache-Control: no-store. HTML
success/error responses require X-Frame-Options DENY/SAMEORIGIN and a non-report-only
CSP with these directives:

| CSP directive | Accepted source values |
|---|---|
| default-src | self or none |
| script-src | self or none |
| object-src | none |
| base-uri | none |
| form-action | self or none |
| frame-ancestors | self or none |
| script-src-elem / script-src-attr, if supplied | self or none |

Values above mean the literal quoted CSP tokens. Duplicate directives, wildcards,
unsafe-inline and unsafe-eval in checked script directives fail. The test checks
header policy and canary escaping, not full browser policy enforcement.

GET search forms need no CSRF token. Detected mutating forms (including a button
formmethod override) must contain a 32- or 64-character Django csrfmiddlewaretoken.
Absent/invalid-token POST requests to read-only web routes must return 405. A 403
cannot prove a public route is read-only. These checks do **not** prove that Django
CSRF middleware is installed or that a future authenticated write interface resists
CSRF; those checks require a separate authorized session/endpoint contract.

## Evidence classification and limits

PASS applies only to the exercised synthetic model/target and identified fixture.
FAIL records a controlled oracle/transport code and HTTP statuses. INCOMPLETE means
mutation probes or correlated logs are missing. An initial connection/deadline
failure is SERVER_NOT_AVAILABLE; remaining probes are NOT_RUN. A connection/deadline loss during the matrix fails the current case and marks subsequent probes NOT_RUN. Exit codes are
0/1/2 for complete pass/failure/unavailable or incomplete, respectively.

Observable snapshots include every public fixture field and count. They cannot
prove there were no private database changes, queued tasks, emails, provider calls,
audit writes or cache entries. No external provider access is enabled by this lane.
Repeated privacy search and no-store headers test the public interface; shared
cache isolation and backend log completeness need coordinator-owned integration
inspection. A correlated test log proves only the supplied log was inspected.

No original source import, PostgreSQL migration, requester confidentiality beyond
seeded canaries, production performance, authenticated RBAC/CSRF, browser XSS
execution or owner-policy acceptance is certified here. No count/latency claim may
be transferred from the synthetic server to Django or production.
