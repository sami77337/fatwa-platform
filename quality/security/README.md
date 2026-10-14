# S4 standalone negative-test harness

This issue #5 harness checks a disposable **local** public fiqh source catalog.
It never grants permissions, starts Django, changes a database schema, follows
redirects, loads credentials or calls external providers. The HTTP test double is
confined to tests and is not an implementation of S0's backend.

Runtime: **Node.js 24.16.0 (tested here)** with built-in TypeScript stripping and node:test. No npm
install, package manifest, root dependency change, Django import or Python runtime
is needed for the standalone tests. The target backend remains S0's Django
5.2/Python 3.13/PostgreSQL development foundation.

From the repository root, run the synthetic tests:

~~~powershell
node --test --test-reporter=tap quality/security/tests/contract.test.ts quality/security/tests/suite.test.ts quality/security/tests/transport.test.ts quality/security/tests/cli.test.ts
~~~

These tests validate the oracles against safe and deliberately unsafe in-memory
models, plus ephemeral loopback HTTP test servers. They cover positive browsing,
negative requests, state snapshots, schema failures, escaped private canaries,
transport limits and evidence sanitization. A passing synthetic test does not mean
a Django endpoint or PostgreSQL integration passed.

Probe the default local server without mutating requests:

~~~powershell
node quality/security/cli.ts --base-url http://127.0.0.1:8000 --output docs/security-review/evidence/local-server-probe.json
~~~

If a local server is available, this command checks the public synthetic fixture
and read-only probes. Mutating probes remain NOT_RUN. If the initial fixture
preflight cannot connect, it records SERVER_NOT_AVAILABLE and stops. A mismatched
fixture or response is FAIL, rather than a universal denial being treated as a pass.

After S0 integration, seed/reset a disposable target with the exact public fixture
and isolated synthetic private canaries. Configure its **test-only** logger to
include the X-S4-Run-ID request header and exclude credentials, user data and
unnecessary request/query content. Place its current run log in the owned evidence
directory. Then run the full matrix:

~~~powershell
node quality/security/cli.ts --base-url http://127.0.0.1:8000 --profile quality/api_contract/proposed-profile.json --fixture quality/api_contract/synthetic-catalog.json --disposable-synthetic-target --log-file quality/security/evidence/test-only.log --output docs/security-review/evidence/integrated-synthetic-run.json
~~~

The disposable flag enables rejection probes using synthetic POST/PUT/PATCH/DELETE
bodies. The harness validates seeded public state before running them and compares
observable catalog state around every attempted write. A defective backend could
still mutate unobservable private state, so the flag is appropriate only for an
isolated, resettable synthetic target. No real requester data is needed or allowed.

Logs are read **after** the HTTP matrix and must contain this run's marker. An old,
unrelated or absent log cannot satisfy the log oracle. Keep the input test-only log
local; it is not copied into reports. Reports contain case IDs, statuses, numeric
HTTP statuses, controlled failure codes, time, Git HEAD/branch and input/code SHA256
values. They contain no HTTP bodies, header values, cookie values or raw exception
messages. Output and log files must stay in S4-owned evidence directories.

Exit codes: 0 = all selected synthetic runtime probes and the correlated log check
passed; 1 = contract/security/configuration failure; 2 = unavailable server or
incomplete evidence. Every report retains SYNTHETIC_DEVELOPMENT_ONLY and
NOT_DEPLOYED / GATES_HOLD. A runtime PASS never advances owner policy gates.

Only explicit loopback origins are accepted: 127.0.0.1, localhost or [::1], using
HTTP/HTTPS without credentials, path prefixes, queries or fragments. localhost is
pinned to 127.0.0.1; proxy environment variables are unused. HTTPS retains normal
certificate verification. Default per-request deadline is 2 seconds, response body
cap is 256 KiB and header cap is 16 KiB. No cookie jar or authorization headers are
used. A failing preflight causes subsequent probes and log checks to be NOT_RUN.

Read the [contract](../api_contract/README.md),
[acceptance oracle](../../docs/security-review/ACCEPTANCE_ORACLE.md),
[threat model](../../docs/security-review/THREAT_MODEL.md) and
[actual local review](../../docs/security-review/REVIEW_20261013.md) for coverage and
limitations. Static type checking, browser execution of CSP/DOM behavior,
authenticated CSRF, shared-cache internals and private database side effects need
separate integration evidence and are not established by this harness.
