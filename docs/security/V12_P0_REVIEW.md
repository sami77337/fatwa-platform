# V12 P0 independent security review — PASS on 5aff9ba

## Final independent P0 re-review (2026-11-18)

**Verdict: PASS for the requested P0 security review on exact commit
`5aff9ba3cce35241b3ded27ed3428e0d4ecad768`.** No unresolved P0 blocker was found
in the reviewed recovery/admission/source-rights/publication boundaries. The
previously blocking multi-result expiry probe now passes on both PostgreSQL
majors. This is a scoped engineering/security finding, not formal product
acceptance, authorization for production, or a statement that arbitrary privileged
database/Python access is controlled. Gate B NOT_PASSED, C/D/E HOLD, Phase01 BLOCKED,
NOT_DEPLOYED and the owner's engineering reference remain unchanged. This lane
has not started P1/P2; the coordinator owns the subsequent campaign decision.

### Exact head, scope and evidence

Verified remote integration branch and `refs/pull/231/head` both resolve to the
SHA above. Used a clean detached worktree `/tmp/v12-security-rereview` at that
commit. Read the full repair diff and updated integration evidence. This follow-up
changes only this report on `codex/20261117-v12-security-review`; no product code,
committed tests, CI, configuration or GitHub settings changed here. Historical
failures below are retained verbatim as dated checkpoints, not current blockers.

Independently verified [V12 CI run 44203281971](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971)
belongs to the exact commit and that jobs `134462617865` (PG17) and `134462617398`
(PG18), including exact-head verification, succeeded. The verifier source includes
the 14 original independent review tests and all 10 new collection regressions.
The coordinator reports 183 functional/security + 8 strict recovery + 16 encrypted
V11 + 22 isolated V10 tests per major. Those broader counts are CI evidence, not
new local executions by this reviewer. Exact-commit workflow metadata also confirms
successful V10 (`44203281782`) and V11 (`44203281992`) runs. No browser suite was
rerun locally because this repair did not change a browser implementation.

The earlier reviewed maintenance/recovery implementation, management boundaries,
answer-media hooks, shared settings/workflows and original 14 independent tests
are unchanged between `37c58a4` and `5aff9ba` (verified by git diff). The citation
clone's existing admission hook remains before copying; the changed citation code
adds guards around read compositions. Consequently the unchanged maintenance and
recovery suites were not repeated locally in this pass. Their prior independent
results and current exact-head CI remain separate evidence.

### Independent focused results on 5aff9ba

| Execution on fresh owned synthetic clusters | PG17.12 | PG18.7 |
| --- | --- | --- |
| Original unmodified `/tmp/v12_batch_probe.py` reproducer plus the 10 integrated affected regressions | **11 PASS**, 9.787s | **11 PASS**, 10.040s |
| Two additional independently authored concurrent withdrawal probes | **2 PASS**, 1.486s | **2 PASS**, 1.416s |

Thus **13 focused executions passed on each major**, including the original
independent reproducer and two new independent methods. This count deliberately
distinguishes reviewer-authored probes from the integrator's 10 tests. Runtime:
Python 3.13.16; the same PG17.12 and PG18.7 binaries documented earlier. The PG18
local build is not claimed to duplicate every CI build feature.

The first batch verifies metadata/text-source search, category/material filters,
pagination, GET/HEAD, staff results, expiry during final validation or filtering,
and related/research/citation composition. The original two-item probe is unchanged
from the failed `37c58a4` run: A's source grant expires during B's projection,
A's detail is denied, B remains readable, and the catalog now contains only B,
total 1 and only B's category.

The new probes use actual separate PostgreSQL connections and canonical mutation
services, not raw rights edits or a synthetic return-value mock. While the reader
projects the second publication, another connection attempts either rights REVOKE
or publication WITHDRAW on the first. `pg_blocking_pids(writer_pid)` positively
identifies the reader as a blocker, and the writer cannot complete until the
batch transaction exits. This proves serialization, not an expectation of
retroactively invalidating a read that preceded a committed withdrawal. After the
write commits, both probes assert: first detail denied; only B remains in anonymous
and staff lists; source-title search total 0; category list contains only B;
PAGE_SIZE=1 gives total 1, page 1 only B, page 2 empty, and no next-page flag.
Both worker connections close and no worker exception remains.

### Repair assessment and remaining limits

- Anonymous collection revalidates all candidates before deriving search results,
  facets or pages, filters against one final clock, and refuses the response if a
  retained deadline expires while filtering. Canonical case locks remain held
  throughout. The previous premature result collection is no longer observable
  in the unchanged reproducer.
- Staff publication collection now retains deterministic case locks for the batch,
  revalidates exact source grants and staff identities, and applies equivalent
  final expiry checks. There is no new grant or fallback permission.
- The deadline hook validates the same exact source snapshot, case, current rights
  revision and usage, returning the existing deadline only after permission is
  established. The Boolean compatibility hook delegates to it.
- Citation, knowledge and research compositions add an execution-local expiry
  guard. Successful reference/transcript checks contribute to every enclosing
  guard, which resets its context on success or exception. It does not create
  source authority for source-free answers or replace source/case/publication
  checks. Integrated affected tests pass for nested composition and state cleanup.

No current blocker remains from SEC12-01 through SEC12-06 within this tested
application perimeter. This conclusion does not erase their baseline failures or
the earlier `37c58a4` collection leak. Direct privileged SQL, arbitrary Python/ORM
outside supported boundaries, production deployment and real-user data remain
outside the evidence. No main-protection setting was changed or asserted.

### Reproduction and durable evidence

All new probes were kept in `/tmp` to honor report-only ownership. The full original
probe is preserved below; the new concurrency module is appended after it. Run
from a checkout of `5aff9ba3cce35241b3ded27ed3428e0d4ecad768` with matching PG binaries:

```sh
PYTHON=/workspace/fatwa-platform/.venv/bin/python
PG_BIN=/tmp/v9-pg/usr/lib/postgresql/17/bin
PG_MAJOR=17
PYTHONPATH="/tmp:$PWD" V12_PG_BIN="$PG_BIN" "$PYTHON" \
  infra/dev/with_casework_postgres.py --pg-bin "$PG_BIN" --major "$PG_MAJOR" \
  --settings config.settings.campaign_review -- "$PYTHON" manage.py test \
  v12_batch_probe.BatchExpiryProbe.test_prior_item_expiry_during_later_projection \
  tests.casework.test_v12_catalog_expiry --verbosity 2
PYTHONPATH="/tmp:$PWD" V12_PG_BIN="$PG_BIN" "$PYTHON" \
  infra/dev/with_casework_postgres.py --pg-bin "$PG_BIN" --major "$PG_MAJOR" \
  --settings config.settings.campaign_review -- "$PYTHON" manage.py test \
  v12_withdrawal_probe.WithdrawalProbe.test_rights_revocation_waits_for_batch_then_removes_all_metadata \
  v12_withdrawal_probe.WithdrawalProbe.test_publication_withdrawal_waits_for_batch_then_removes_all_metadata \
  --verbosity 2
# Repeat with PG_MAJOR=18 and PG_BIN=/tmp/v12-pg18-built/bin.
```

Captured logs: `/tmp/v12-newhead-pg{17,18}.log` and
`/tmp/v12-withdrawal-pg{17,18}.log`. All listed methods report `ok`; exact summaries:

```text
PG17.12: Ran 11 tests in 9.787s — OK
PG18.7:  Ran 11 tests in 10.040s — OK
PG17.12: Ran 2 tests in 1.486s — OK
PG18.7:  Ran 2 tests in 1.416s — OK
System check identified no issues (0 silenced).
```

## Previous integrated-head re-review — BLOCKED on 37c58a4 (2026-11-17)

**Verdict: BLOCKED, not PASS**, on exact integration commit
`37c58a4a420a961b1adf486d52c42672cc70c8eb` (Draft PR #231).
The original single-publication expiry regression is repaired, but a focused
two-publication regression reproduces stale source metadata/count disclosure on
both PostgreSQL 17.12 and 18.7. P0 is not closed; P1/P2 remain blocked. No acceptance,
gate change, production authorization or revised engineering estimate is implied.

Both `refs/heads/codex/20261117-v12-integration` and `refs/pull/231/head` were
checked with `git ls-remote` and matched this SHA. Testing used a clean detached
worktree at that exact commit. This follow-up changes **this report only** on
`codex/20261117-v12-security-review`; no implementation, tests, configuration or
GitHub setting was modified. Earlier findings and failed evidence below remain
historical evidence and are not presented as current failures without rechecking.

### Verified fixes and focused execution

Read the integrated P0 evidence, strict settings, exact-head CI workflow, and
affected implementation. `_current` now rechecks source eligibility after yield;
`browse` appends the individual projection only after that context exits.
Both clone helpers and GET `_budget` require admission before reading/copying or
writing. The installed management execution boundary guards supported commands
and rejects unsupported strict administration. `campaign_strict` enables
maintenance, source rights and required encryption, and disables V10 compatibility.
The legacy recovery exception remains confined to its explicitly separate test
profile. These repairs do not grant protection from privileged SQL or arbitrary
Python/ORM entry outside the supported application boundary.

Independently checked [CI run 44199692350](https://github.com/sami77337/fatwa-platform/actions/runs/44199692350)
and its association with the exact commit: jobs `134450282075` (17) and
`134450283328` (18), including the exact-head verification step, completed
successfully. The workflow explicitly checks out and asserts the PR head SHA.
The 14 committed review tests in this head match this review branch unchanged.
CI success and its reported broader counts are distinct from the following local
execution; this follow-up did not rerun the full suite or browser journeys.

| Independent checks on exact 37c58a4 | PG17.12 | PG18.7 |
| --- | --- | --- |
| Six focused committed tests: single-item post-projection expiry; both clone admission hooks; GET without outer middleware; flush before destructive SQL; plaintext downgrade denial; real encrypted snapshot positive control | 6 PASS (0.861s) | 6 PASS (0.762s) |
| Additional two-item catalog expiry probe, reproduced below | 1 FAIL (0.680s) | 1 FAIL (0.603s) |

The six-test run used `infra/dev/with_casework_postgres.py`, fresh owned clusters,
`config.settings.campaign_review`, and explicit method labels from
`test_rights`, `test_maintenance`, plus the two `test_recovery` methods. The tests
enable the relevant strict boundary explicitly; the review bootstrap profile is
not represented as a serving profile. Local logs are
`/tmp/v12-final-independent-pg{17,18}.log` and
`/tmp/v12-batch-expiry-pg{17,18}.log`. Portable failure excerpts and the complete
temporary probe are included below because `/tmp` files are not delivered artifacts.

### SEC12-03 follow-up: earlier result expires during later projection

Affected location: `apps/library_preview/services.py`, `browse`, lines 271-315
at the reviewed SHA. The result collection retains an already appended item when
its rights expire during a later item's projection. The final `_recheck(selected)`
checks only PreviewPolicy, not current rights for all collected results. Case locks
serialize explicit revocation but do not stop clock expiry.

Reproduction uses two independently approved synthetic publications from distinct
cases, both explicitly permitted by the 30-minute preview policy. Publication A
has a cited source with one-minute READ/CITE/RELATE/PREVIEW_METADATA rights;
publication B has no citations. Positive control returns two results before expiry.
The clock advances monotonically by two minutes only while projecting B. After
`browse` returns, A's detail is correctly denied and B's detail still succeeds,
confirming that the source grant expired while preview authorization remained
valid. Nevertheless, the captured catalog response still contains A's title,
category and exact source metadata, including work/heading/edition/publisher/page,
and reports total 2 rather than 1. The response does not contain A's body; this
finding specifically proves metadata, category and count disclosure.

Both majors fail the same assertion after those positive/negative controls:

```text
test_prior_item_expiry_during_later_projection ... FAIL
AssertionError: 2 != 1
categories: ['Second synthetic category', 'تصنيف تجريبي']
total: 2
stale references: work_title='مرجع اصطناعي للاختبار',
  heading_title='فَرْعٌ تَجْرِيبِيّ', edition_title='طبعة اختبار',
  publisher='ناشر اصطناعي', printed_page=2
PG17.12: Ran 1 test in 0.680s — FAILED (failures=1)
PG18.7:  Ran 1 test in 0.603s — FAILED (failures=1)
```

Required integration action: revalidate the entire collected response's source
eligibility at the final catalog boundary, and remove denied results before
deriving categories, filters, pagination and totals (or fail the response closed).
Retain exact source/version/use predicates, case locks and independent preview
policy. Review the analogous multi-result staff library aggregation as well; it
also has per-item checks, but this follow-up has not dynamically proved a separate
staff-library failure. Add the two-item regression to integration coverage and
rerun affected checks on both majors at the new head before seeking P0 closure.
No implementation repair was attempted outside this lane's ownership.

### Executable temporary probe

Save the Python block at the end of this report as `/tmp/v12_batch_probe.py`.
Run from a checkout of the reviewed commit, with the repository root on PYTHONPATH.
The probe reuses only canonical synthetic fixture setup and contains independent
assertions. It was kept temporary to honor the report-only follow-up instruction.

```sh
# Set these to your isolated interpreter and matching PostgreSQL installation.
PYTHON=/workspace/fatwa-platform/.venv/bin/python
PG_BIN=/tmp/v9-pg/usr/lib/postgresql/17/bin
PG_MAJOR=17
PYTHONPATH="/tmp:$PWD" V12_PG_BIN="$PG_BIN" "$PYTHON" \
  infra/dev/with_casework_postgres.py --pg-bin "$PG_BIN" --major "$PG_MAJOR" \
  --settings config.settings.campaign_review -- "$PYTHON" manage.py test \
  v12_batch_probe.BatchExpiryProbe.test_prior_item_expiry_during_later_projection \
  --verbosity 2
# The second run used PG_MAJOR=18 and PG_BIN=/tmp/v12-pg18-built/bin.
```

## Historical review record (preserved)

Scope: `tests/v12_security_review/**` and this report only. No implementation,
shared configuration, CI, GitHub protection setting, source data or other lane changed.
Base PR #230 and remote ref verified: `5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`.
Branch: `codex/20261117-v12-security-review`; V11 branch/history preserved.
AGENTS.md and the V11 functional scope/decisions, recovery contract and rights
boundary tests were read. Repository `.agents/skills` is absent.

**Historical checkpoint: at the initial review, the integrated V12 head had not
been tested. The current exact-head verdict is recorded above.**
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
All are captured real executions, containing synthetic fixture information only;
trailing whitespace from unittest subtest status lines is normalized for git checks.
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

## Temporary two-publication regression source

```python
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority, Directory
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.source_rights import services as rights
from tests.v12_security_review.test_rights import RightsP0Tests


class BatchExpiryProbe(RightsP0Tests):
    def test_prior_item_expiry_during_later_projection(self):
        receipt = cases.intake_case(
            original_question="Synthetic second question",
            source_event_id="batch-expiry-2", requester_id="synthetic-second",
            idempotency_key="batch-expiry-2", synthetic_fixtures_only=True,
        )
        common = dict(case_id=receipt["case_id"], subject_id="editor",
                      provider=Directory([receipt["public_ref"]]), synthetic_fixtures_only=True)
        answer = cases.save_answer(**common, expected_revision=1,
                                   expected_evidence_version=1, text="Synthetic second answer")
        cases.record_decision(**common, answer_id=answer["answers"][-1]["id"],
                              expected_revision=2, expected_evidence_version=1,
                              action="APPROVE", note="synthetic")
        with override_settings(FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(receipt["public_ref"])):
            second = publications.create_edition(
                **common, expected_revision=3, expected_evidence_version=1,
                title="Synthetic second publication", category="Second synthetic category",
                body="Synthetic second editorial body")
            publications.act(**common, edition_id=second["id"], action="REVIEW", reviewed=True)
            publications.act(**{**common, "subject_id": "publisher"},
                             edition_id=second["id"], action="APPROVE")
        row = PublicationEdition.objects.get(pk=second["id"])
        policy = PreviewPolicy(
            (*self.policy.publications, PublicationGrant(str(row.pk), row.content_sha256)),
            self.policy.references, self.policy.valid_until, True)
        clock = [timezone.now()]
        future = clock[0] + timedelta(minutes=2)
        original = preview._projection

        def delayed(selected, edition):
            result = original(selected, edition)
            if str(edition.pk) == str(row.pk):
                clock[0] = future
            return result

        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy):
            self.assertEqual(preview.browse()["total"], 2)
            with (patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
                  patch.object(preview, "_projection", side_effect=delayed)):
                result = preview.browse()
                # The earlier grant is actually denied now, while preview policy
                # and the independently approved second publication remain valid.
                with self.assertRaises(preview.PreviewUnavailable):
                    preview.read(self.edition["id"])
                self.assertEqual(preview.read(str(row.pk))["id"], str(row.pk))
                self.assertEqual(result["total"], 1, result)
                self.assertEqual([item["id"] for item in result["items"]], [str(row.pk)])
                self.assertEqual(result["categories"], [row.category])
```

## Independent concurrent withdrawal probe source

Save as `/tmp/v12_withdrawal_probe.py`; run only the two explicit method labels above.

```python
"""Independent two-connection probes, exact reviewed head, synthetic data only."""
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import patch

from django.db import connection, connections

from apps.experimental_publication import services as publications
from apps.library_preview import services as preview
from apps.source_rights.models import RightsRevision
from tests.casework.test_v12_catalog_expiry import CatalogExpiryTests


class WithdrawalProbe(CatalogExpiryTests):
    def _concurrent_withdrawal(self, action):
        original = preview._projection
        ready, done = Event(), Event()
        worker_pid, errors, threads = [], [], []
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            reader_pid = cursor.fetchone()[0]

        def writer():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '8s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    worker_pid.append(cursor.fetchone()[0])
                ready.set()
                action()
            except BaseException as exc:
                errors.append(exc)
            finally:
                connections.close_all()
                done.set()

        def during_later(selected, edition):
            result = original(selected, edition)
            if edition.pk == self.second.pk and not threads:
                thread = Thread(target=writer, daemon=True)
                threads.append(thread)
                thread.start()
                self.assertTrue(ready.wait(3), errors)
                deadline = monotonic() + 3
                blocked = False
                while monotonic() < deadline and not done.is_set():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [worker_pid[0]])
                        blocked = reader_pid in cursor.fetchone()[0]
                    if blocked:
                        break
                    sleep(0.01)
                self.assertTrue(blocked, errors)
                self.assertFalse(done.is_set())
            return result

        try:
            with patch.object(preview, "_projection", side_effect=during_later):
                before_commit = preview.browse()
            # The write is serialized after this read, not silently committed
            # between the first and second projections.
            self.assertEqual(before_commit["total"], 2)
        finally:
            for thread in threads:
                thread.join(10)
        self.assertTrue(done.is_set())
        self.assertEqual(errors, [])
        with patch.object(preview, "PAGE_SIZE", 1):
            for page in (1, 2):
                result = preview.browse(page=page)
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["categories"], [self.second.category])
                self.assertEqual([item["id"] for item in result["items"]],
                                 [str(self.second.pk)] if page == 1 else [])
                self.assertFalse(result["has_next"])
        with self.assertRaises(preview.PreviewUnavailable):
            preview.read(str(self.first.pk))
        self.assertEqual(preview.browse(query=self.heading.title_original)["total"], 0)
        self.assertEqual([r["id"] for r in publications.library(**self.staff)],
                         [str(self.second.pk)])

    def test_rights_revocation_waits_for_batch_then_removes_all_metadata(self):
        revision = RightsRevision.objects.get(source_id=self.source["id"],
                                              case_id=self.common["case_id"])
        self._concurrent_withdrawal(lambda: self.decision({"id": str(revision.pk)}, "REVOKE"))

    def test_publication_withdrawal_waits_for_batch_then_removes_all_metadata(self):
        self._concurrent_withdrawal(lambda: publications.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=str(self.first.pk), action="WITHDRAW"))
```
