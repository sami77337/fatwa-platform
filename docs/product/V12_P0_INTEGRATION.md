# V12 P0 integration — engineering checkpoint and retained history

Base: PR #230, `5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`.
Branch: `codex/20261117-v12-integration`. V11 is preserved.


## Current checkpoint

Draft PR: [#231](https://github.com/sami77337/fatwa-platform/pull/231), above #230.
The integrated P0 workflow on `6abaeb91e58902e4ae1e028cf8d81828f75618da`
**passed on both PostgreSQL 17.12 and 18.7**: 173 functional/security checks,
8 strict recovery checks, 16 encrypted V11 regressions, 22 isolated V10 recovery
compatibility checks per major. The 14 independently authored security probes are
included in the 173, not counted a second time. System/migration drift checks passed.

- [Exact-head P0 run 44198979109](https://github.com/sami77337/fatwa-platform/actions/runs/44198979109)
- [PG17 evidence](https://github.com/sami77337/fatwa-platform/actions/runs/44198979109/artifacts/14379219907)
- [PG18 evidence](https://github.com/sami77337/fatwa-platform/actions/runs/44198979109/artifacts/14379409269)

A final V10 browser-fixture correction preserves its selected isolated profile at
the offline operation, after LiveServerTestCase's extra settings holder. It changes
no recovery permission or application behavior. The affected browser passed locally
(1/1, 28.035s; Chromium sandbox=False). Protected Chrome must be judged from final
CI, not this local result. Its prior exact-head CI failure is retained below.
The latest PR head and final checks supersede this earlier exact-head checkpoint.

**P1/P2 are not started.** The independent reviewer supplied the failing contracts
and reviewed lane heads; those tests now pass in the integrated matrix. The final
reviewer's report still says OPEN and has not yet been updated against this repaired
integration head. Deliver this head for that independent check before opening P1.
This is an engineering checkpoint, not formal acceptance or a new completion estimate.

Actual external task identifiers (no invented task URLs):

| Task | Thread |
|---|---|
| Recovery | `6afc9ae5-b338-8191-bcff-7654953230ed` |
| Maintenance | `6afc807f-d7cc-8191-ad01-1d971f53f019` |
| Rights | `6afc808d-03cc-8191-8171-3bfbe0ad201c` |
| Independent security | `6afc80af-d6a4-8191-a0ac-08f14e1b300b` |

The remainder is chronological evidence; earlier pending/failed checkpoints are
retained as history and are not the current passing P0 matrix result.

P1 is not started. Its prerequisite is integrated P0, passing affected PostgreSQL
17 and 18 checks, an independent security review and a recorded integration SHA.
CI results are engineering evidence, never owner acceptance. Owner reference
remains 79% ±8; Gate B NOT_PASSED, C/D/E HOLD, Phase01 BLOCKED, NOT_DEPLOYED.

## Integration-owned administration boundary

When `FATWA_RECOVERY_MAINTENANCE_REQUIRED=True`, the command overrides in
`apps/intake_workflow/management/commands/` refuse `flush`, `loaddata`, `dumpdata`,
`shell`, `dbshell`, `clearsessions`, `createcachetable` and `test` at `execute`,
before native command checks, writes, file creation, interactive prompts or
exports. Error: `STRICT_ADMINISTRATION_UNSUPPORTED`. Session administration is
closed even though Django's session app is not installed in this composition.
Tests run in the isolated bootstrap/test profile, never as live strict-runtime
administration. General-purpose unscoped dumps are not encrypted recovery bundles.

`migrate` holds application admission around its whole native execution, including
checks, transactions, post-migrate signals and command finalization. A frozen or
unconfigured boundary produces `MAINTENANCE_ADMINISTRATION_UNAVAILABLE` instead
of an implementation traceback. Custom intake/review and source import commands
retain their native guarded service transactions; they do not add an outer atomic.

Legacy compatibility delegates to Django only when maintenance is explicitly not
required in that isolated profile. This is not an administration bypass advertised
for a running strict application. Fresh owned test-database bootstrap is offline,
with no HTTP server, queue worker or GC, before the strict application is enabled.

## HTTP and storage coverage to integrate

- The topmost MaintenanceGuard encompasses the downstream response, including
  GET/HEAD budgets and cookie creation. Strict streaming is refused; an iterator
  cannot borrow an expired synchronous admission.
- `casework_web.guard._budget` now additionally requires existing admission before
  its transaction. Omitting the topmost middleware cannot silently write a GET
  budget. The profile's staff/requester sessions are signed cookies, not a separate
  Django session database. Admission covers their response generation.
- Existing public services for casework, attachments, answer media, source intake,
  requester replies/access recovery, review, delivery queue/receipts/tracking,
  transcript links and team updates participate in application admission. Their
  native commit boundaries are preserved. The maintenance lane audits and hardens
  these shared wrappers; its contract and tests are pending integration.
- Private filesystem put/restore/orphan collection and attachment/answer storage
  conversion already participate. Source bindings are held through their native
  commit. The P0 final checks must cover FROZEN conversion and GC and callback
  lifetime, not just HTTP POST.
- Recovery control transitions and verified new-target restoration use their
  separate offline operation contracts. They cannot admit source writers.
- External privileged SQL, arbitrary Python using ORM internals, direct
  MigrationExecutor and direct filesystem manipulation are outside this
  cooperative application boundary. No database privilege firewall is claimed.

## Focused local evidence so far

PostgreSQL 17.12, isolated disposable cluster:

- `tests.casework.test_v12_administration`: 7/7 passed. Actual command registry
  resolves to the overrides; denied commands preserve the source receipt and do
  not create an export. The migration signal observes DRAINING until it returns.
  GET without middleware and GET while FROZEN cannot change budgets or cookies.
- The affected V11 migration-boundary test was updated to assert the documented
  CommandError rather than a raw admission exception: 1/1 passed.
- Ruff on changed integration files: passed. A first wider lint invocation found
  pre-existing import order in two untouched Wave7 commands; no unrelated churn.

PG18, external lane integration and independent security review: pending. This
checkpoint is not P0 closure and does not authorize P1 by itself.

## Integrated handoffs and final-check candidate

Delivered lane heads (preserved as commits in the integration history):

- Recovery: `a067bb58cb8068d5ec8689069668e4cbddc641be`.
- Maintenance: `9b5fafffbbf937444cc5df81f1130a98bf26f502`.
- Rights: `ca86c0dc89534ff4a8ff06665a25a8bf98440de3`.
- Independent security: `e25b2345d48c18eec839d07db5eb6fd4fcb40e52`.

The maintenance hook is now installed from IntakeWorkflowConfig into the shared
Django BaseCommand execution boundary. The reviewed allowlist is enforced for
CLI, normal call_command and command-instance invocation; explicit stock command
overrides additionally reject specialized execute paths. Arbitrary calls to handle
or arbitrary custom Python remain unsupported. The casework GET budget and both
internal clone helpers assert existing admission before database work.

Historical SQLite outbox/source journal paths explicitly refuse opening or
initializing storage when maintenance is required. Those files cannot silently
join a PostgreSQL/private-original recovery cut. Unconfigured pure legacy tests
retain their separate historical behavior.

`config.settings.campaign_strict` selects required maintenance, source rights and
encryption without provisioning authorities, control, identity or storage. It is
closed when unconfigured. Stopped-writer test bootstrap remains separate; the V11
human rehearsal explicitly enables the same strict policy before serving. The
V10 CI uses the exact dedicated compatibility settings. V11 recovery fixtures now
seed canonical records without producing a legacy plaintext bundle, then encrypt.

Historical combined PG17 first run: **56/57 passed, one failed**. Independent
SEC12-03 reproduced expiry after projection even on the delivered rights head.
The integration repair rechecks publication source eligibility after yield, and
only appends library results after the context successfully exits. The staff
library also rechecks after projection. Thus an expired item cannot remain in
body, source metadata, search result, category or count. Shared V11 expectations
were tightened for the new independent publication rights requirement, not relaxed.

Focused post-repair PG17 rights batch: **36/36 passed**. V11 encrypted-only fixture
regression: **16/16 passed**. Additional integration tests cover unknown command
instances, actual cold strict CLI, internal clones and excluded legacy stores.
The complete final candidate is tested by `infra/dev/v12_verify.py` and the V12
P0 workflow on each major. Final matrix and independent final-head review remain
pending; P1 is still closed at this checkpoint.

Local PG18.7 was built under `.local/runtime/pg18` from Debian's source archive
SHA256 `441dfae4280cae3e0425e5f876f80559fb0731c140f1aae22b3e5a54d0411bfd`.
No host packages, production settings or GitHub protections were changed. The
PGDG index returned HTTP403 and apt had no package candidates; locally extracted
build tools and the verified Debian source were used instead. These preparation
failures are not test passes.

The first complete verifier invocation on `43c9c4c` failed before Django test
execution on both majors: the worker was launched by file path, so its Python
import path omitted the repository root (`No module named config`). The launcher
now invokes that worker as `-m infra.dev.v12_verify`. No application assertion was
reported as passed by that failed invocation; both matrix legs must run again.

On `7f0a60c`, both PostgreSQL majors passed 173 functional/security tests (including
all 14 independent review probes), 8 strict recovery tests and 16 encrypted V11
regressions. The final legacy compatibility stage failed in fixture setup before
executing tests: Django override_settings masks SETTINGS_MODULE with None, so the
policy correctly rejected plaintext despite the process selecting the isolated
compatibility module. The shared fixture and V10 browser test now preserve the
module actually selected by their process when applying test overlays. Neither
policy flags nor the production recovery gate were relaxed. Only compatibility
and directly affected fixture checks need local repetition; CI rechecks the head.

The isolated compatibility rerun on each major executed 22 tests: 21 passed and
one independent-server restore failed because that historical test hard-coded the
ordinary settings module for its child server. It now explicitly selects the same
V10-only test profile for that isolated child; the one affected test passed on
PG17 (5.812s) and PG18 (5.772s). The successful 21 were not rerun manually.

CI history on `3f93998`: FAST9 integrated local development journey run
44198655774/job134446690319 passed its service and HTTP steps but failed before
browser creation with Playwright TimeoutError at launch (10s), sandbox enabled.
There were no page assertions, page errors or network requests yet. This is a
recorded startup failure with cause not established, not a passing browser test
or an assumed flake. The next exact-head CI run must supply its own result.


CI V10 browser run44198979013/job134447798997 passed 67 functional and 22 recovery
checks, then failed at the offline snapshot because LiveServerTestCase adds another
settings holder after class-level overrides. The fixture now preserves the actually
selected module at that operation only. Protected CI must verify the final head;
local affected browser passed as recorded above. V11's protected workflow and FAST9
startup both passed on6abaeb9. The earlier FAST9 startup timeout is not erased.

## Re-review block on 37c58a4: multi-result expiry (P0 remains open)

The independent re-review report at `3b7157c0e6c94f17311e0a22d853723354938784`
is preserved by cherry-pick `806abc4`. Its PG17.12/PG18.7 reproduction disproved
this document's earlier single-item claim for **collections**: A's rights expired
while B was being projected, yet A's metadata/category/count remained. Green CI
on 37c58a4 and the earlier 14 probes did not establish P0 closure. P1/P2 remain
blocked. Local baseline reproduction also failed both new anonymous/staff batch
checks (2 tests, 2 failures on PG17, 1.266s); that failure is retained here.

The repair revalidates all collected publications after the last projection,
before search/filter/facets/counts/pagination. Both anonymous and scoped staff
libraries retain canonical case locks throughout aggregation. The exact existing
source-rights validation now also supplies its existing grant expiry; a single
clock after the final validation pass removes earlier grants that expired during
later checks. Expiry during subsequent filtering refuses the entire response.
No renewal, cached permission, fallback rights or new publication approval exists.

Analogous collections were inspected: direct citation search/suggestions/history,
knowledge navigation and research search/open now retain an execution-local bound
from successful exact reference/transcript permission checks and refuse the read
if any such grant expires before the composition returns. Nested bounds are reset
on success and exception. This is additional to identity, case scope, source pins,
independent publication approval and preview policy. It is not an authorization
entry point. Rights review/bootstrap and withdrawal retain their separate policy.

`tests.casework.test_v12_catalog_expiry` preserves the reviewer's two-publication
scenario and adds source/edition/page search, category/material filters, page
boundaries, GET/HEAD, staff results, expiry during the final validation and filtering,
and related/research/citation compositions. It is included in the existing V12 CI
matrix; no unrelated test suite is manually rerun for this repair. The first
focused batch passed 42/42 on PG17.12 (23.443s) and PG18.7 (23.309s); the expanded
initial nine regressions passed 9/9 on PG17 (9.350s). These preliminary results
precede the final affected-head run and are not a closure verdict.
