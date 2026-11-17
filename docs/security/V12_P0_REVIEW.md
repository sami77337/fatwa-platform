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
| CTRL12-06 | Supported encrypted capture still succeeds and verifies, with only ciphertext/COMPLETE and no auto-resume | PASS on17/18 | Retain |

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

## Initial baseline evidence matrix

At the initial evidence checkpoint, production code under review was the exact
PR230 base above and no repair branch had yet been published. The subsequent
published-head follow-up below supersedes that availability observation.
Across focused runs there are **11 distinct contracts per PostgreSQL major:
6 PASS,5 FAIL**. Unaffected suites were not rerun. The failures are open findings,
not suppressed or relabeled as success.

| Run | Result | Durable evidence |
| --- | --- | --- |
| PG17.12 initial10 |5 PASS/5 FAIL,1.815s | `tests/v12_security_review/evidence/pg17_base.txt` |
| PG17 tightened monotonic expiry |1 FAIL,0.337s | `evidence/pg17_expiry_monotonic.txt` |
| PG17 flush actual execution boundary |1 FAIL,0.081s | `evidence/pg17_flush_execution.txt` |
| PG18.7 final10, including both tightened probes |5 PASS/5 FAIL,1.897s | `evidence/pg18_base.txt` |
| PG17 encrypted positive control |1 PASS,0.343s | `evidence/pg17_ciphertext_control.txt` |
| PG18 encrypted positive control |1 PASS,0.295s | `evidence/pg18_ciphertext_control.txt` |

Evidence paths abbreviated `evidence/` are relative to `tests/v12_security_review`.
All are captured real executions, containing synthetic fixture information only.
The new positive-control test initially expected a nonexistent `verified` boolean;
the existing API returns `state=VERIFIED`. Both initial runs errored at that test
assertion after successful capture/verification, then passed after correcting it.
Those initial local logs remain `/tmp/v12-security-ciphertext-pg17.log` and
`/tmp/v12-security-ciphertext-pg18.log`; they are test-author errors, not product
findings. No implementation protection was weakened to make a test pass.

PostgreSQL18.7 was built locally from Debian's upstream source archive
`postgresql-18_18.7.orig.tar.bz2`, SHA256
`441dfae4280cae3e0425e5f876f80559fb0731c140f1aae22b3e5a54d0411bfd`, into
`/tmp/v12-pg18-built` with `--without-icu --without-readline --without-zlib`.
This is a real18.7 server, not a version mock; no extension/performance or CI
parity claim is made. The Debian binary package required unavailable GLIBC2.43
and libraries; apt.postgresql.org was proxy-blocked403. Build helpers were
extracted under `/tmp` (initial missing m4/libsigsegv resolved), without system
package/configuration changes. PG17 used the existing17.12 binary extraction.

Ruff check/format and `git diff --check` pass for this lane. No migrations,
production switches, real data/messages/keys or GitHub settings were changed.

## Published-head independent follow-up — P0 still OPEN

Read the recovery contract/evidence, maintenance contract/inventory and rights
P0 contract at the exact heads below. Used detached temporary worktrees, copied
only this lane's tests, and did not merge/edit implementation code in this branch.
The candidate worktrees are not the final unified campaign checkout.

| Actual source head | Independent affected checks per major | Result |
| --- | --- | --- |
| Integration `95e8091ef9f9a8a8da9ad41a4f7febd4c70677c1` | Six original maintenance contracts, plus omitted-outer-middleware GET check | **7 PASS** onPG17/18 across focused runs |
| Recovery `a067bb58cb8068d5ec8689069668e4cbddc641be` | Legacy plaintext denial + real encrypted positive control | **2 PASS** onPG17/18 |
| Maintenance `9b5fafffbbf937444cc5df81f1130a98bf26f502` | Callback exception, outer atomic rejection, stranded transaction/hook cleanup | **3 PASS** onPG17/18; final cleanup probe rerun separately |
| Rights `ca86c0dc89534ff4a8ff06665a25a8bf98440de3` | Revoked HTTP/body/metadata/count closure; policy separation; mid-response expiry | **2 PASS / 1 FAIL** onPG17/18 |

Durable files: `evidence/integration_pg{17,18}.txt`,
`evidence/recovery_pg{17,18}.txt`, `evidence/rights_pg{17,18}.txt`,
`evidence/missing_middleware_{base,integration}_pg{17,18}.txt`,
`evidence/stranded_transaction_{base,maintenance}_pg{17,18}.txt`.
All paths relative to `tests/v12_security_review`.

Additional independent regressions:

- **SEC12-04:** a leaked atomic/native transaction survives both normal and
  exceptional scope exit on the base. The corrected maintenance head closes the
  raw connection with acknowledged rollback and discards queued callbacks before
  releasing admission. The test records connection closure and callback count
  **before its own safety cleanup**, then verifies no row was committed. Both
  baseline subcases fail; both repaired subcases pass on17/18. The initial draft
  probe incorrectly used Django on_commit with manual autocommit-off (unsupported);
  that produced fixture errors on the base. It was replaced by a legitimately
  registered callback in an abandoned atomic; only corrected results are counted.
- **SEC12-05:** with strict mode on but outer middleware omitted, the base GET
  returns200 and reaches its throttle writer. The integration head's
  `_budget.require_admission()` rejects with503 before that write. FAIL→PASS17/18.
- **SEC12-06:** `clone_parts_for_new_answer` and `clone_citations_for_new_answer`
  still lack their required internal admission check on the base/current95e8091
  integration tree. The added boundary test traps their first source-read call,
  with consistent lineage-shaped arguments and a real FROZEN control; it does not
  perform arbitrary DB writes or claim an internet-accessible endpoint. Both
  helper probes fail on17/18 (`evidence/clone_boundary_base_pg{17,18}.txt`).
  These are the mandatory integrator hooks already identified in the maintenance
  lane inventory. Insert `require_admission()` before helper queries/copies and
  retain normal admitted canonical flows; no change to those files was made here.

There are now **14 distinct regression methods** in this lane. Against the old
base, across targeted runs, **6 PASS / 8 FAIL on each major**; two methods contain
multiple separately reported subcases. This is not a combined-head run.

### Remaining blocking expiry finding (SEC12-03)

On the delivered rights head, `library_preview.services._current` invokes
`publication._require_publication_sources(...)` before `yield`, but only
`_recheck(selected)` after it. An exact source grant can therefore expire while
projection/history is built, with still-valid case/preview authority, and the
already assembled publication/body/source metadata escapes. The monotonic-clock
regression still fails on both majors (1.077s/1.053s for the three-test rights runs).
Recheck the exact current source eligibility at the return boundary, converting
failure to `PreviewUnavailable`; cover browse and reference/detail projections
without exposing stale items, counts or metadata. This lane cannot edit that code.
A passing explicit revocation-before-request test does not close this finding.

### Shared compatibility assertions for the integrator

The two historical `tests/casework/test_v11_rights_boundaries.py` expectations
must follow the new policy, not relax it:

- `test_preview_metadata_is_independent_and_filtered_before_search_counts`:
  READ+CITE+RELATE without PREVIEW_METADATA now hides the **entire** edition;
  expect total0/detail unavailable until all required publication uses exist.
- `test_relationship_read_and_relate_are_independent_and_current`: give the valid
  publication READ+CITE+PREVIEW_METADATA throughout the RELATE-only scenario.
  Losing READ makes the publication itself unavailable (not merely an empty link
  list). Losing RELATE alone must still hide the relationship while retaining an
  otherwise eligible publication. Preserve independent review and current pins.

No shared assertion was changed by this lane. The integrated head must contain
all three implementation branches, administrative/clone/GET connections, explicit
strict rights/encryption settings, the new migration, and the expiry repair before
claiming P0 closure or startingP1. Current independent green results on separate
heads are necessary evidence, not that integrated verdict.

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
