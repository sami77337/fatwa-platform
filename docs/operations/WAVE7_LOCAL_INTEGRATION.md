# Wave7 available-producer QA integration

This is local integration of the accepted foundation and the published E1/E2/E3/E6
files. Publication remains on owner hold. E4 is unavailable: no Wave7 E4 module,
route, settings flag, label or substitute is installed. This increment does not
constitute assembled Wave7 acceptance or independent review.

Use Python 3.13, Node 24, the existing pinned requirements, and the separate
`config.settings.wave7_test` profile only on an owned disposable synthetic service.
The default/public profile is unchanged. The available E2 route is
`/dev/editorial-preview/persisted`, named `wave7_editorial_review`; it precedes the
legacy generic preview identifier in `config.wave7_urls`. Only the separate Wave7
profile registers it, and `FATWA_WAVE7_REVIEW_READ=1` explicitly enables reads.
Other strings leave reads disabled. GET/HEAD use the actual E2 reader; unsafe
methods cannot invoke the reference verifier, intake writer or review transition.

## Pure collection on Ubuntu and Windows

The C6 matrix now runs these commands in addition to the existing dispatcher and
full C1/C2/C3/importer discovery:

```sh
python -B tools/dev/wave7_qa.py --suite pure --json .local/qa/c6/wave7-pure.json
python -B tools/dev/wave7_qa.py --suite editorial-off --json .local/qa/c6/wave7-editorial-off.json
python tools/dev/wave4_node.py tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
python tools/dev/wave4_node.py tests/acceptance/wave7/reference_assertions.test.mjs
python tools/dev/wave3_qa.py --standalone --require-integrated --reports .local/qa/c6
```

The first two commands sanitize inherited credentials/connection overrides and
force `PGPORT=1`. They use Django's ordinary runner with no DB-using labels. The
actual E1 CLI check is registered under the separate Wave7 app profile, and never
opens a database. The E2 default-off suite uses ordinary test settings. Each
required module must import and collect at least one case before any execution;
another module's green cases cannot mask zero collection. Missing modules,
execution/count mismatches, skips and expected failures fail the new Wave7 gate.
Bounded JSON records exact SHA, clean/dirty state, platform, counts and skips.
The E6 Node collection is 18 cases: six CDP, two keyboard and ten exact-reference
assertions, including negative status/citation/row/batch/pointer/locator cases.
The new ten-case file has its own mandatory nonzero gate, so the existing eight
cases cannot mask its absence or zero collection.

Legacy importer reporting still discloses its real source skips; no owner source
acceptance is inferred. The D6 port-1 manifest remains unchanged.

## PostgreSQL 17 and 18

The B6 `wave7-foundation` matrix preserves its dedicated role, fixed profile,
literal loopback, ownership initializer, migration checks, fresh test DB runner
and cleanup policy. It now runs:

```sh
python tools/dev/wave7_qa.py --suite database --json .local/qa/wave7-foundation/tests.json
```

Actual required labels (94 cases at the assembled producer heads):

| Module under `tests.` | Cases |
| --- | ---: |
| `wave7_foundation.test_database` | 21 |
| `wave7_foundation.test_review_regressions` | 4 |
| `wave7_foundation.test_lossless_db` | 9 |
| `wave7_foundation.test_reference_service` | 15 |
| `wave7_foundation.test_service_integration` | 2 |
| `intake_workflow.test_database` | 15 |
| `editorial_demo.test_wave7_review_db` | 16 |
| `editorial_demo.test_wave7_read_db` | 12 |

The permanent E3 module implements the producer's DB proposal, including exact
original text/byte offsets, six conflicting C2 fields, malformed/numeric/null
pointers, duplicates, missing collections, missing headings, wrong archive hash
and printed location, and the same-title/wrong-ancestor regression. It executes
an actual failing PostgreSQL SELECT and proves a real first-row bulk UPDATE rolls
back after an injected failure. Identical replay issues zero UPDATEs. No source
trigger is disabled; negative catalog records are inserted before standard seed
and never repaired or overwritten.

The two shared integration cases use E1 import, commit, E3 verification, E2
transition/read and the actual shared GET route. They verify historical intake
findings remain unchanged, current reference state is read, batch UUID isolation,
GET filter/page/detail/return state, default-off and unsafe method boundaries.

## Mandatory actual E6 invocation

The independent `wave7-acceptance` PG17/18 job uses its own
`wave7_synthetic_e6_ci` / `test_wave7_synthetic_e6_ci` target, role
`wave7_synthetic`, `FATWA_WAVE7_E6_ACCEPTANCE=1`, the existing write guard flags,
and E2's explicit read flag. It imports E6's actual `LABELS` table and requires
nonzero collection for every label before initializing only its empty service.
These commands run in separate steps, retaining failures and artifacts:

```sh
python tests/acceptance/wave7/run.py --suite service
python tests/acceptance/wave7/run.py --suite workflow-service
python tests/acceptance/wave7/run.py --suite browser-baseline
python tests/acceptance/wave7/run.py --suite browser
```

Set `E6_WAVE7_ARTIFACTS` to a distinct directory for every command. CI uses
`E6_BROWSER=/usr/bin/google-chrome` with the protected flags in the producer's
actual harness. No fallback DOM test, missing engine, HTTP 200, empty suite or
baseline result satisfies the persisted browser gate. Service=6 cases;
workflow-service=2 cases; baseline browser=1 Python wrapper / 4 browser cases;
persisted browser=1 wrapper / 8 browser cases. The existing Wave6 B6 job remains
unchanged. Both new jobs upload identity, logs and browser artifacts on failure.

Cloud's installed Chromium currently aborts at the SUID sandbox check. Both
browser commands therefore exit nonzero, with 4 and 8 browser cases NOT_RUN.
Do not change system security or disable sandbox protections. Actual supported
browser execution and a fresh independent combined review remain required.

## Pending E4 integration and gates

The locally reported E4 head is not fetchable/published, so its proposed
`tests.integration.api.test_wave7_workflow_reads` and
`tests.integration.ui.wave7_workflow_reads_db` labels are not wired. After actual
files are provided, review their APIs and append the real labels to the correct
pure/DB group; add their routes to this same Wave7 URLconf only with the actual
E4 functions. Do not substitute empty modules, guessed implementations, optional
imports, a second conflicting URLconf or fabricated acceptance. E2-to-E4 reader
adaptation belongs to the relevant producers/coordinator.

Windows CI and GitHub Actions are NOT_RUN while publication is held. Real-source
read-only checks, independent combined review and source/product acceptance are
NOT_RUN. `NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
