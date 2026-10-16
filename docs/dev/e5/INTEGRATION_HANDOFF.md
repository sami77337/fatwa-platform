# E5 actual integration-only patches

These patches are **NOT APPLIED in E5**. The coordinator applies them after
assembling the actual lane code. E5 fetched/inspected the published files
read-only and did not merge or cherry-pick any neighboring lane into E5.
No missing-module fallback or optional PASS is provided.

| Producer | Actual inspected commit | Required contract |
| --- | --- | --- |
| E2 PR51 | `b1289215a8cc83a20a70caed553bf664dea7be40` | No-DB `tests.editorial_demo.test_synthetic_batch` (11) and `tests.editorial_demo.test_review_fixes` (6), alongside the original three |
| E3 PR53 | `26dba43149129e3f0cbd5689247cc3da9fe5d3c2` | DB-only `tests.reference_links_db.test_catalog_adapter`, actual file and initializer verified |
| E4 PR55 | `411965fc94329e0c206101144a788351b63e245e` | No-DB `tests.integration.api.test_e4_catalog`, eight methods verified |
| E6 PR52 | `a541cd9b3693e034173242f44fdb33dbb7358e2b` | Guarded `run.py`, static-files-aware server, service/assets/review-batches/regression/browser modules and artifacts |

Apply from the assembled checkout, preserving the E5 lane's own commits:

```text
git apply --check docs/dev/e5/e2-actual-label.integration.patch
git apply docs/dev/e5/e2-actual-label.integration.patch
git apply --check docs/dev/e5/e4-actual-label.integration.patch
git apply docs/dev/e5/e4-actual-label.integration.patch
git apply --check docs/dev/e5/e3-e6-actual.integration.patch
git apply docs/dev/e5/e3-e6-actual.integration.patch
```

The E2/E4 patches add their actual no-DB Django labels to D2/D4 in
`tools/dev/wave4_suites.json`. D2 requires all five labels: the original
preview/pipeline_preview/worklist modules plus synthetic_batch and review_fixes.
Both new modules subclass SimpleTestCase. Missing files or zero cases fail
through the existing D6 checks; no DB label is added. Preserve all existing labels; rerun D6 with its
sanitized unreachable PGPORT=1 after E1/E2/E3/E4 assembly. The E4 real-PG module
`tests.integration.ui.test_e4_postgres` is already discovered by B6's existing
UI directory; never add it to C6/D6. New pure E1/E3 files are already covered
by their existing directory discovery.

The E3/E6 patch adds E3's DB label to **both** `qa.py:APP_TESTS` (qa_worker)
and the B6 PG17/18 workflow. Both qa_worker and CI also require nonzero
collection of that exact E3 adapter module before the combined run, so an empty
adapter module cannot hide among existing B6 cases. E6 DB modules are invoked only by its guarded
`run.py`, never by C6/D6 or the unguarded B6 Django discoverer. B6 creates a
separate `e6_synthetic` / `test_e6_synthetic` database on its own disposable CI
service. E6 acknowledgement is explicit. An occupied E6 database fails.

The browser patch uses Python 3.13, Node 24, the standard Ubuntu runner's
existing `/usr/bin/google-chrome`, and logs the engine version. A missing engine
fails. No browser installation, grant, security-setting change, protection
bypass or automatic engine fallback is included. The protected engine's actual
availability and interaction results are NOT_RUN until the assembled CI runs.

E6's six Python target-guard tests and six Node transport tests precede its
actual `run.py`, `run.py --assets`, `run.py --review-batches`,
`run.py --regressions` and `run.py --browser --review-batches` gates. The
new assets module has two live-server methods and review-batches has three.
The combined browser invocation requires the tenth batch-identity journey. Node uses
the existing zero-case guard; each service/regression/browser log must report
nonzero unittest cases. Pipe failures propagate. A regression failure remains
a job failure while the browser can still run if the synthetic service passed.
The existing always-uploaded B6 artifact captures `.local/qa/e6/` logs, JSON,
console/network trace, and screenshots only when produced by real interaction.

All three patches passed sequential applicability checks in a disposable copy.
JSON/AST labels, B6/C6/D6 YAML, Bash syntax and embedded Python compilation
passed. This is configuration evidence only: **combined-SHA execution NOT_RUN**.
No patch-level test outcome is presented as adapter or browser acceptance.

E6 reported the pinned baseline filter-only API/SSR regression FAIL and Cloud
Chromium startup BLOCKED (nine browser journeys NOT_RUN). E4 reports the
corresponding production fix. The assembled run must prove that fix and expose
any remaining browser failures. The updated E6 README reports review-batch checks against the initial E2
`feb70f0...` snapshot. The coordinator must run those same mandatory checks
against corrected E2 `b1289215...`; E5 has not run or modified E6 browser code.
Latest parent-supplied E1 is `c38c7ed6b120de07730cb34a51678f6929305249`; its
existing pure directories remain automatically discovered. No E1 merge was
performed in E5.

Coordinator final matrix: full importer, dispatcher regressions, C6/D6 on
Ubuntu+Windows, full B6 PG17/18 with actual E3/E4 modules, E6 on the exact
assembled SHA, then fresh independent review. Keep repeated suite invocations
separate rather than inventing one distinct-test total. Real-source acceptance
is separate and NOT_RUN: the four source importer skips remain explicit.
No next wave is dispatched. `USAGE_NOT_OBSERVED / NOT_DEPLOYED / GATES_HOLD`.
