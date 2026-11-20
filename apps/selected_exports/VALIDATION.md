# Selected exports — observed local development evidence

Base: `da920d3`; isolated branch `review/20261120-selected-exports`. Only
`apps/selected_exports/**` is owned by this lane. No remote push, main merge,
deployment, shared guard exception or policy promotion is part of this change.

Runtime: Python 3.13.5, Django 5.2.18, pinned repository dependencies, fresh owned
PostgreSQL 17.11 and 18.7 clusters through `with_casework_postgres.py`, using
`apps.selected_exports.settings`. All source contents and identities are invented
fixtures populated through existing canonical services.

## Observed results

| Run | Result |
| --- | --- |
| Core services and native HTTP on PostgreSQL 17 | 16/16 passed, 10.091 s |
| File loss/crash/worker/relationship/recovery-helper cases on PostgreSQL 17 | Five passed; two ledger cases initially stopped on an eagerly evaluated test default, corrected below |
| Focused real source-rights ledger cases on PostgreSQL 17 | 2/2 passed, 1.478 s |
| Repeated-download terminal-capacity regression on PostgreSQL 17 | 1/1 passed, 20.337 s; CANCEL at sequence 95, real-time EXPIRE/status at 96 |
| Combined core/durability/ledger/capacity suite on PostgreSQL 18 | 24/24 passed, 35.143 s |
| Final SQL null/shape, immutability and lifecycle check on PostgreSQL 17 | 1/1 passed, 0.518 s |
| Same final SQL check on PostgreSQL 18 | 1/1 passed, 0.566 s |

The combined run includes the original 16 and eight durability/security cases;
these are 24 distinct tests, not the sum of every repeated run. A final narrow
SQL-null/shape hardening uses the existing database-integrity test rather than
inventing additional functional-unit counts; its final checks are recorded above.

The tests inspect actual ZIP bytes and every manifest file checksum, decode all
three formats, compare exact original source content, preserve canonical case
events, and assert absence of private case originals, raw requester capability,
credentials, provider configuration and storage keys. Private media tests verify
actual original bytes. One test unlinks an actual filesystem object, verifies an
explicit partial result, restores the same exact original and retries the pinned
scope. Unrequested files are distinguished from requested unavailable files.

The source-rights tests use actual independently reviewed READ grants and retain
the ledger's rejection of EXPORT. Separate export and sensitive/media grants are
required. Expiry and a late actual ledger revocation deny download/generation;
the failed artifact and nested revocation roll back while a generic failed
attempt remains auditable. The worker command completes an existing durable job
without a browser. A simulated process interruption leaves a persisted lease;
retry after its real expiry produces one later result and rejects stale completion.

Independent integration review identified that legitimate download history could
consume the SQL limit and prevent cancellation/expiry. The service and PostgreSQL
state machine now reserve terminal capacity. The actual regression executes 90
downloads from the READY event, refuses another new event at sequence 94, then
successfully cancels and expires without relaxing the 96-event constraint.

## Native HTTP and browser

The HTTP journey uses the existing login, staff identity/case scope, original
CaseworkGuard, CSRF middleware, POST endpoint and final response policy boundary.
It selects actual catalog results, saves a signed preview, queues/prepares a
durable task and downloads the verified ZIP. It tests forged scope, task expiry,
cross-case/owner denial, CSRF, and permission changes during final template render.
No guard or request-budget bypass is used. Isolated URL composition supplies the
entry form on the already permitted staff GET route; the integrating campaign
owns its normal navigation/dispatcher.

The protected Chromium test was attempted locally. Chromium stopped **before UI**
with `process_singleton_posix.cc:297: socket() failed: Operation not permitted`.
It also reported the executor's ptrace restriction. No unprotected retry was
performed and no local browser acceptance pass is claimed.

Hosted module: `apps.selected_exports.browser_tests`. A successful protected run
writes `.local/qa/functional-completion/export-browser/result.json` with
`status=PASS`, `sandbox=true`, widths 320/1280, alongside screenshots and trace.
The actual journey uses native keyboard/form actions, a real downloaded ZIP,
source immutability and a subsequent current-grant denial. A missing proof file
or startup failure is not a pass.

## Recovery and scope limitations

`recovery_support.populate()` and `verify_restored(pins)` were exercised with
nonempty job/event/artifact tables and independently reviewed source rights on a
separate synthetic case. The helper verifies artifact replay, restored immutable
guards and denial without current identity/export grants. This local helper test
is not an encrypted recovery drill; the integrating lane owns that fresh-database,
fresh-process evidence and complete schema inventory.

No real-content licensing, external scheduler, production role policy, arbitrary
archive import, XLSX/Parquet, video, public dataset or complete corpus coverage is
claimed. The seven target points require assessment against these explicit
functional boundaries and the final integrated commit. **NOT_DEPLOYED / GATES_HOLD.**
