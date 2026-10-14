# S4 threat model: public fiqh source catalog

Issue #5, independent development review. NOT_DEPLOYED / GATES_HOLD.
Gate B NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED. U03 (48 clauses) and U10
(28 clauses) remain OWNER_APPROVAL_PENDING. This document grants no permissions.

## Assets, actors and trust boundaries

Assets are public source titles and hierarchy edges, printed citations and edition
attribution, public counts/search results, browser execution context, and evidence
that no synthetic private artifact is disclosed. Private requester cases, contact
data and unapproved fatwas are **outside the public catalog** and remain disabled.

An anonymous browser or adversarial HTTP client supplies paths, query strings,
methods and forged headers. The future Django boundary validates these inputs,
returns an explicit public schema, and reads the public reference store. ORM/SQL,
HTML templates, browser policy, cache storage and development logs are distinct
boundaries. This harness observes HTTP and a supplied test-only log; it cannot
inspect the database, production cache or middleware from that vantage point.

The harness itself reads typed, runtime-validated synthetic JSON inputs. Its HTTP
transport restricts origins to loopback, pins localhost to 127.0.0.1, ignores proxy
environment settings, refuses credentials, bounds response bytes/headers and
request time, and never follows redirects. An ephemeral test HTTP model exercises
the transport without providing a Django application or privileged operation.

Reference 622 is one Hanbali source work's table of contents. It is neither a
published fatwa corpus nor the approved global taxonomy. Source edition metadata
must remain stable and visibly distinguish that scope. The local fixture uses
fabricated titles and explicitly unverified synthetic edition labels.

## STRIDE review

| Threat | Concrete abuse | Current oracle / harness control | Residual evidence needed |
|---|---|---|---|
| Spoofing | Claim MUFTI, ORGANIZER_ADMIN, ORGANIZER or DOMAIN_TRANSACTION using request headers | Forged role probes remain denied; no cookies/authorization sent; exact public schema | Future authenticated identity/authorization contract and deny-default tests, deferred |
| Tampering | Write to catalog or invoke publishing/workflow/grant/delivery APIs; alter parent edges or edition | All four mutating methods denied; public before/after/final snapshots preserve all fixture values | Private DB, audit/queue/provider side-effect inspection on disposable integrated target |
| Repudiation | Fabricate runtime PASS, substitute fixture/edition, or inspect unrelated logs | Real HTTP statuses, controlled failures, Git SHA/branch, code/input hashes, current run marker; absent dependencies never PASS | Coordinator verifies actual target reset/seed receipt, private canary presence and log completeness |
| Information disclosure | Leak requester contacts or unapproved fatwas through API, counts, errors, cache hits or logs | Exact allowlist/fixture equality; known canaries in bodies/headers/logs including common encodings; hidden lookup/count=0; no-store and repeated search | Real integrated private isolation and shared-cache inspection; known canaries are not exhaustive data-loss detection |
| Denial of service | Request huge pages/queries, ambiguous duplicate parameters, slow or oversized responses | Boundary/error cases; per-request 2-second deadline, 256 KiB body and 16 KiB header cap; abort remaining matrix after connection/deadline loss | S0 query-count/resource tests and request-rate controls on PostgreSQL; no production benchmark claimed |
| Elevation of privilege | Treat draft workflow/permission rows as active endpoints; exploit SQL text, CSRF, XSS or unsafe redirects | Literal SQL queries; escaped positive title/query; restrictive CSP/frame/referrer/nosniff; unavailable write methods; no automatic redirects | Actual ORM parameterization review, browser CSP/DOM tests and authenticated CSRF validation for future write interfaces |

The cache header policy is strict for this synthetic run. If S0 later intentionally
caches public source data, S4 must review cache keys, tenant/auth separation,
negative-result behavior and shared-cache contamination before revising that
oracle. A cache hit returning an empty seeded private lookup does not establish
absence of private artifacts in cache internals.

The log oracle reads only an explicitly supplied bounded test-only log after the
matrix, requires the current run marker and searches for private synthetic
canaries. Reports preserve only the log SHA256 and result. Missing/unrelated logs
remain NOT_RUN/FAIL. The harness cannot establish that an application logged every
request or that it never wrote a private artifact to another sink.

## Explicitly deferred interfaces

- Authenticated RBAC, permission administration, requester/user administration,
  private cases, scholarly rulings/approval and fatwa publishing.
- Draft workflow transitions and DOMAIN_TRANSACTION execution. The latter is an
  internal atomic effect, never a runnable principal.
- AI fatwa writing/approval and external ChatGPT/provider integration.
- Telegram/WhatsApp delivery and the old Telegram bot.
- Production migrations, deployment, owner policy acceptance and other sciences
  awaiting owner-supplied sources.

D-067 gives MUFTI and ORGANIZER_ADMIN equivalent administrative hierarchy while
only MUFTI may create or approve substantive scholarly rulings; ORGANIZER has
configurable lower operational access. This distinction creates **no active grant**
here. All 70 historical permission rows remain DENY_DEFAULT,
NONE_CANDIDATE_BINDING_ONLY. The 58 workflow transitions remain documentation.
U03/U10 pending clauses cannot be converted into endpoint behavior or acceptance.

## Scope of this evidence

Synthetic tests prove that the QA harness accepts a conforming fabricated target
and rejects the exercised unsafe variants. They do not certify Django/PostgreSQL,
the original source ZIP, full-corpus integrity, browser execution safety, production
performance or requester privacy beyond the provided canaries. The actual local
server probe and environment blockers are recorded in
[REVIEW_20261013.md](REVIEW_20261013.md).
