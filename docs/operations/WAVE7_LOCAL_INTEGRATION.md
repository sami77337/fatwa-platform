# Wave7 available-producer QA integration

This is local integration of the accepted foundation, published E1/E2/E3/E6 files,
and the coordinator's hash-verified internal E4, E6-P2 and E2-adapter patches.
Publication remains on owner hold. E4 APIs/context and E2's actual loader are
now integrated. This increment does not constitute assembled Wave7
browser acceptance or independent review. Patch provenance is recorded in
`docs/dev/wave7/e5/E4_PATCH_INTEGRATION.md`; no unpublished producer commit is
claimed as remote ancestry.

Use Python 3.13, Node 24, the existing pinned requirements, and the separate
`config.settings.wave7_test` profile only on an owned disposable synthetic service.
The default/public profile is unchanged. The available E2 route is
`/dev/editorial-preview/persisted`, named `wave7_editorial_review`; it precedes the
legacy generic preview identifier in `config.wave7_urls`. Only the separate Wave7
profile registers it. `FATWA_WAVE7_SYNTHETIC_READS=1` explicitly enables the common
`WAVE7_READS_ENABLED` and aliased `WAVE7_REVIEW_READ_ENABLED` settings. Other strings
leave both disabled; the former review-only environment flag alone enables
neither. GET/HEAD use the actual E2 reader; unsafe
methods cannot invoke the reference verifier, intake writer or review transition.

## Pure collection on Ubuntu and Windows

The C6 matrix now runs these commands in addition to the existing dispatcher and
full C1/C2/C3/importer discovery:

```sh
python -B tools/dev/wave7_qa.py --suite pure --json .local/qa/c6/wave7-pure.json
python -B tools/dev/wave7_qa.py --suite editorial-off --json .local/qa/c6/wave7-editorial-off.json
python -B tools/dev/wave7_qa.py --suite workflow-off --json .local/qa/c6/wave7-workflow-off.json
python tools/dev/wave4_node.py tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
python tools/dev/wave4_node.py tests/acceptance/wave7/reference_assertions.test.mjs
python tools/dev/wave3_qa.py --standalone --require-integrated --reports .local/qa/c6
```

The first three commands sanitize inherited credentials/connection overrides and
force `PGPORT=1`. They use Django's ordinary runner with no DB-using labels. The
actual E1 CLI check is registered under the separate Wave7 app profile, and never
opens a database. E2's six and E4's eight default-off cases use ordinary test settings. Each
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

Actual required labels (115 cases with the actual E2 adapter):

| Module under `tests.` | Cases |
| --- | ---: |
| `wave7_foundation.test_database` | 21 |
| `wave7_foundation.test_review_regressions` | 4 |
| `wave7_foundation.test_lossless_db` | 9 |
| `wave7_foundation.test_reference_service` | 15 |
| `wave7_foundation.test_service_integration` | 5 |
| `intake_workflow.test_database` | 15 |
| `editorial_demo.test_wave7_review_db` | 16 |
| `editorial_demo.test_wave7_read_db` | 12 |
| `editorial_demo.test_wave7_e4_adapter_db` | 8 |
| `integration.ui.wave7_workflow_reads_db` | 10 |

The permanent E3 module implements the producer's DB proposal, including exact
original text/byte offsets, six conflicting C2 fields, malformed/numeric/null
pointers, duplicates, missing collections, missing headings, wrong archive hash
and printed location, and the same-title/wrong-ancestor regression. It executes
an actual failing PostgreSQL SELECT and proves a real first-row bulk UPDATE rolls
back after an injected failure. Identical replay issues zero UPDATEs. No source
trigger is disabled; negative catalog records are inserted before standard seed
and never repaired or overwritten.

The shared integration cases use E1 import, commit, E3 verification, E2
transition/read and the actual shared GET route. They verify historical intake
findings remain unchanged, current reference state is read, batch UUID isolation,
GET filter/page/detail/return state, default-off and unsafe method boundaries.
The new E4 cases compare actual shared API results to the SSR read context,
preserve source text and current citations, and check disabled/HEAD/invalid/unsafe
requests through the real registered URLs. A further case verifies the browser's
question-only search plus READY_FOR_EDITOR filter across repeated-ID batches,
through the actual adapted E2 loader. The obsolete external-ID query matches zero.

The same separate URLconf registers `wave7_api_batches` at
`/dev/wave7/api/batches`, `wave7_api_items` at `/dev/wave7/api/items`, and
`wave7_api_item` at `/dev/wave7/api/items/<str:ident>`, before legacy patterns.
String identifiers reach the actual JSON UUID validator. Disabled Wave7 handlers
return their fixed JSON 404; the public/default URLconf registers none of them.

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

## Final composition and remaining gates

The actual E4 patch files and eight no-DB / ten DB labels are now wired. Its DB
label is explicit only in the owned Wave7 PG17/18 group; it is never sent to
port-1 C6/D6 discovery. The producer's deliberate DB filename remains unchanged.
E2-to-E4 reader adaptation, including search mode, now comes from the verified
43,383-byte producer patch. Its eight DB regressions are explicitly included.
E5 changes no producer service contract. The E6 browser's desktop/mobile fixture
query is aligned with question-only search and native mode/status controls; exact
citation/row/batch/source assertions remain intact. Full E6 runs are now applicable
to the final clean local head, using the same protected runtime and fresh owned DB.
See `docs/dev/wave7/e5/FINAL_INTEGRATION.md` and the exact-head artifact manifest.

Windows CI and GitHub Actions are NOT_RUN while publication is held. Real-source
read-only checks, independent combined review and source/product acceptance are
NOT_RUN. `NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
