# E5 integration dependency handoff

Final cross-lane wiring is **NOT_RUN / pending assembly**, per Issue50 v1.1.
At initial inspection no Wave6 branches or files were published. This E5 branch
starts at the pinned Wave5 base and does not fabricate neighboring modules,
optional successful fallbacks or combined acceptance.

Apply only after the coordinator assembles the actual lane commits:

1. E2's actual module was verified read-only at PR51, commit
   `feb70f0fe9d0fe71765044045bc5924aa175f676`:
   `tests/editorial_demo/test_synthetic_batch.py` (Python label
   `tests.editorial_demo.test_synthetic_batch`; 11 methods reported by E2,
   NOT_RUN in E5). Apply `e2-actual-label.integration.patch` only after assembly:
   `git apply --check docs/dev/e5/e2-actual-label.integration.patch`, then
   `git apply docs/dev/e5/e2-actual-label.integration.patch`. The patch was
   checked for clean applicability on E5's unchanged base manifest; it adds the
   actual no-DB label to D2's `django` list in `tools/dev/wave4_suites.json`. Keep existing preview, pipeline_preview
   and worklist labels. Run D6 under its sanitized unreachable PGPORT=1. Record
   actual case totals and rerun with actual E1/E3 code. A missing module or zero
   cases must fail; it cannot be conditional PASS.
2. Obtain E3's exact real adapter modules under `tests/reference_links_db/**`,
   including package initializers. Add explicit dotted labels to **both**
   `tools/dev/qa.py:APP_TESTS` (used by qa_worker) and B6's PostgreSQL workflow
   test invocation. Run PG17 and PG18. Do not add them to C6 PACKAGES, the D6
   pure manifest, or `tests/reference_links/**`. The existing pure directory
   remains auto-discovered, so new pure E3 tests already join C6/D6.
3. Obtain E6's actual invocation, runtime/dependency contract, fixture service/DB
   lifecycle and artifact paths from `tests/acceptance/wave6/**`. Add it to the
   existing B6 synthetic PostgreSQL job as appropriate, with Python 3.13 and
   Node 24, actual supported browser engine, timeouts and always-uploaded
   sanitized desktop/mobile results. Keep browser failures nonoptional; retain
   engine/version, executing SHA, interaction counts, console/network evidence
   and traces/screenshots. Never run the legacy owner-catalog browser launcher.
   Do not change Chromium security settings or disable its protections.
4. Run full importer and dispatcher regressions, C6/D6 Ubuntu+Windows, complete
   B6 PG17/18, and E6 on the actual assembled SHA. Report precise duplicate
   invocations separately instead of inventing a unique whole-project total.

The E2 integration-only patch uses the actual published module. E2 was fetched
and inspected without merging/cherry-picking any E2 code into E5. E3/E6 patches
still require their actual files; no guessed labels are provided. The coordinator
may request an E5 follow-up patch after assembling those paths. That patch must be
verified at the assembled SHA, preserve this lane's earlier commit and add no
other lane's production edits.

Real-source acceptance remains separate and NOT_RUN. The four importer skips
are exactly the missing-original-mapping test and the three owner CSV/JSONL/JSON
acceptance tests. This increment did not inspect, reimport or normalize owner
source material. Windows CMD execution and real-browser acceptance cannot be
inferred from Linux regression tests or Node DOM tests.

Independent review is pending the designated reviewer. No next wave is
requested or dispatched. `NOT_DEPLOYED / GATES_HOLD`.
