# V12 P0 integration checkpoint (in progress)

Base: PR #230, `5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`.
Branch: `codex/20261117-v12-integration`. V11 is preserved.

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
