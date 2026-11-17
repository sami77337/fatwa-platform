# V12 P0 independent security review — OPEN

Scope: `tests/v12_security_review/**` and this report only. No implementation,
shared configuration, CI, GitHub protection setting, source data or other lane changed.
Base PR #230 and remote ref verified: `5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`.
Branch: `codex/20261117-v12-security-review`; V11 branch/history preserved.
AGENTS.md and the V11 functional scope/decisions, recovery contract and rights
boundary tests were read. Repository `.agents/skills` is absent.

**This is not P0 closure. The integrated V12 head has not been tested.**
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
Owner reference79% ±8 is unchanged and is not acceptance. No P1 work.

## Independent contracts and findings on the V11 base

These tests express required denial, not expectedFailure/xfail or demonstrations
that pass when a vulnerability exists. They reuse canonical synthetic fixture
setup where needed but contain independent assertions, clock injection and probes.

| ID | Finding / contract | Base observation | Repair owner |
| --- | --- | --- | --- |
| SEC12-01 | Public legacy backup API must not downgrade to plaintext without a separate compatibility opt-in | `service.snapshot(offline=True, synthetic_fixtures_only=True)` produces database.dump, schema.sql and manifest.json even with maintenance required/FROZEN | Recovery lane |
| SEC12-02 | Supported administrative writers must obey the maintenance boundary | Stock `flush` reaches its destructive SQL boundary (probe stops it before execution); `loaddata` commits a synthetic throttle row; `shell` writes a temporary marker while FROZEN | Maintenance/integration lane |
| SEC12-03 | Publication eligibility must remain valid through response projection, not only before it | An independently approved one-minute source grant expires after body/source metadata assembly while the separate 30-minute preview policy remains valid; `preview.read` still returns the publication | Rights/publication integration lane |
| CTRL12-01 | GET/HEAD including throttling cannot write while frozen or disclose control metadata | PASS:503/no-store; throttle rows unchanged; root, database and generation not echoed | Retain |
| CTRL12-02 | Commit callback exception cannot release admission early | PASS: callback holds DRAINING after actual DB commit, nested callback writes finish, exception preserves committed state, subsequent freeze succeeds | Retain |
| CTRL12-03 | Caller-owned outer transaction cannot schedule work after admission release | PASS: outer-atomic scope rejected; callback never registered | Retain |
| CTRL12-04 | Explicit revocation closes publication body and exact-source HTTP paths, list counts and staff library | PASS including GET/HEAD404/no-store and metadata absence | Retain |
| CTRL12-05 | Source rights do not replace independent PreviewPolicy or configured rights authority | PASS | Retain |

SEC12-03 uses a monotonically advanced synthetic clock for the remainder of the
request; it does not revoke rights through raw SQL, bypass case locks, expire
identity, or expire the independent preview policy. Repair must revalidate current
source eligibility at the return boundary and must not merely hide citation badges
while returning a now-ineligible body. Keep unrelated metadata permissions distinct.

SEC12-02 does not execute flush/TRUNCATE. The trap records reaching
`connection.ops.execute_sql_flush`, then raises before SQL. `loaddata` touches only
one synthetic throttle row in a fresh owned test database; shell touches only a
TemporaryDirectory marker. Arbitrary host-level Python/raw SQL remains outside
cooperative application admission and must not be advertised as controlled by it.

## Reproduction and evidence

Use explicit module labels: repository `tests` is a namespace package, so dotted
directory discovery `manage.py test tests.v12_security_review` fails before test
execution (historical `/tmp/v12-security-pg17-base.log`).

```sh
V12_PG_BIN=/path/to/postgresql/17/bin python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- python manage.py test \
  tests.v12_security_review.test_maintenance \
  tests.v12_security_review.test_recovery \
  tests.v12_security_review.test_rights --verbosity 2
```

For18 use its matching binary directory/major and `V12_PG_BIN`. The helper owns and
removes the disposable cluster; never point these tests at a shared/live database.
The downgrade test needs actual matching pg_dump, not a fake dump result.

Initial PostgreSQL17.12 run:10 tests,5 PASS/5 FAIL, no errors
(`/tmp/v12-security-pg17-base2.log`,1.815s). All three administrative probes, legacy
plaintext output and rights-expiry projection were red. The original expiry
injection was then tightened to keep the clock advanced through function return;
the targeted rerun remains FAIL (`/tmp/v12-security-expiry-baseline.log`,0.337s).
The flush trap was moved from SQL planning to the actual pre-execution boundary
so legitimate read-only planning cannot cause a false positive. Later evidence
must name the exact tested source head and these final test versions.

## Integration handoff

Cherry-pick only this test/report lane. Route findings to their implementation
owners; this lane deliberately supplies no production repair. Once repair heads
are published, review their diff and run only affected independent tests against
those exact code heads, using a temporary checkout if needed. Final P0 closure
requires all focused regressions and impacted compatibility checks on the actual
integrated head, both PostgreSQL17/18, with report and CI evidence tied to that SHA.
Never erase the base failures or equate individual branch green with closure.

Main protection was not modified. No supported branch-protection read connector
is available in this session; no assertion is made about its actual settings.
Recommended owner review: required exact-head status checks, review requirements,
restricted bypass/force push and deletion. This report does not authorize changes.
