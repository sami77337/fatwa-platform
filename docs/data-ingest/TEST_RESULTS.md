# S1 actual verification results — 2026-10-13

**NON_PRODUCTION_LOCAL_CHANGES / NOT_DEPLOYED / GATES_HOLD / Phase01 BLOCKED.**

Branch: `codex/s1-fiqh-import-20261013`.
Baseline HEAD: `08f9e25e8ada9af56561d815f74b2c7ec9ba7ead`.
All implementation files are local, uncommitted additions. No commit, push, PR,
merge, deployment or legacy Telegram change was performed.

## Results and limits

| Check | Actual outcome |
| --- | --- |
| Owner archive SHA256 | PASS: exact match with owner pin. |
| Owner archive manifest member hashes | PASS: all 11 listed members match their SHA256 and byte counts. Archive scripts were hashed, never executed. |
| JSONL complete source inspection | PASS using independent Node assertions: 11,397 unique nonblank heading IDs/titles, 32 roots (30 books + 2 introductions), max depth 5, all 11,397 reachable. |
| Original ID/title comparison | PASS: all 11,397 JSONL names/IDs exactly match the original-title CSV. |
| CSV/nested JSON comparison | PASS: all 11,397 titles/IDs, parent edges, printed references and source ordering agree with JSONL. |
| Graph/reference/path checks | PASS using Node assertions: no duplicates, orphans, cycles, ambiguous sibling orders, missing pages or contradictory source paths. Source declared depth/child/leaf values match actual edges. |
| Synthetic fixture identity | PASS: actual fixture hash equals manifest, with 7 unique nodes, 2 roots, 6 direct/1 inferred titles. |
| JSON artifact parsing | PASS: three schema JSON files, two synthetic fixture JSON files, owner manifest and source-inspection JSON parse. This is JSON parsing, not execution of a JSON Schema validation engine. |
| Ownership / existing tracked files | PASS: changed-file inventory is confined to tools/fiqh_import, tests/fiqh_import and docs/data-ingest; no existing tracked files were altered; branch and HEAD unchanged. |
| Whitespace inspection | PASS using Node: no trailing whitespace in deliverable files. |
| Python unittest suite | **NOT_RUN — runtime missing**. Launcher attempts fail before loading any test. There are 59 defined methods: 56 synthetic tests and 3 real-source acceptance tests. |
| Python importer CLI / actual normalized export | **NOT_RUN — runtime missing**. No actual output hash or byte-identical Python rerun pass is claimed. |
| Python syntax, lint, type checks | **NOT_RUN — no Python/tooling available**. Code received manual review only. |
| PostgreSQL / Django integration | NOT_RUN; outside standalone S1 ownership and unnecessary for this package. |
| Upstream SQLite/Lucene verification | NOT_RUN; original 622.db and title.zip are not in the supplied TOC archive. Their hashes in source metadata are declared, not independently verified. |

## Actual failed Python commands

~~~powershell
py -3.13 -B -m unittest discover -s tests/fiqh_import -v
~~~

Actual launcher exit code: **112**.
stdout: empty.
stderr:

~~~text
No installed Python found!
~~~

~~~powershell
py -3.13 -B -m tools.fiqh_import --input tests/fiqh_import/.scratch/owner-622-r1.jsonl --manifest docs/data-ingest/owner-622-r1-jsonl.manifest.json --profile real-622 --adapter owner-622-r1 --output tests/fiqh_import/.scratch/owner-622-r1.normalized.jsonl --report tests/fiqh_import/.scratch/owner-622-r1.audit.json
~~~

Actual launcher exit code: **112**, with the same stderr and empty stdout.
No normalized export or Python audit report was produced.

Additional runtime checks: `py -0p` reported "No installed Pythons found!";
`python --version` could not spawn (ENOENT). A cached former Python 3.14 path
also did not exist. Docker was not running; WSL could not enumerate a usable
distribution. A temporary official Python 3.13 download failed; no runtime was
installed or committed. The command-runner tool itself failed to initialize,
so local read-only commands and file work used the available Node tool.

## Actual source identity

Archive:
`_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip`

- Bytes: 3,216,947.
- Actual SHA256: `82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce`.

JSONL member:
`FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl`

- Bytes: 5,934,496.
- Actual SHA256: `37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14`.
- Original-title CSV SHA256: `13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9`.
- Source counts by depth: 1 → 32, 2 → 475, 3 → 10,673, 4 → 215, 5 → 2.
- Actual normalized Python output SHA256: **unavailable / NOT_RUN**.

The archive was discovered in the ignored _codex_input directory after the
initial tracked-file inventory. An earlier source-missing assumption was corrected.
Its contents were read as data only. No build/extraction scripts or instructions
from the archive were executed. The raw local JSONL copy is under ignored
tests/fiqh_import/.scratch and is absent from git status.

Synthetic fixture: `synthetic-five-level-v1`,
`tests/fiqh_import/fixtures/synthetic-five-level.json`,
actual SHA256:
`fa37b33efc506f3deb9f8d2f32223ef8bce85c9748fb840061b359437b3c94d3`.

Independent checks used Node fs/crypto/zlib/assert to read the ZIP central
directory, decompress selected members in memory, verify manifest hashes,
parse the heading JSONL and CSV, compare original names, walk the full hierarchy,
and verify path/parent/order/page consistency. They did not emulate or execute
the Python export. Machine-readable evidence is [source-inspection.json](source-inspection.json).

## Checks of local state

The following read-only Git commands actually ran:

~~~text
git branch --show-current
git rev-parse HEAD
git --no-optional-locks status --short --untracked-files=all
git diff --name-only
git check-ignore -- tests/fiqh_import/.scratch/owner-622-r1.jsonl _codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip
~~~

Branch/HEAD matched the values above; existing tracked-file diff was empty.
Raw source paths were confirmed ignored. A no-index whitespace check against NUL
also printed no whitespace findings; its exit 1 represented the new-file diff
and Git printed its local LF/CRLF conversion warning. The independent Node
whitespace scan is the recorded passing whitespace check.

## Remaining execution blocker

An installed Python 3.13 runtime is needed to execute the 59 tests and real-source
CLI, record the actual normalized output SHA256, and prove byte-identical reruns.
The source attachment is present and verified; it is not a remaining blocker.
The implementation must not be called acceptance-complete until these Python
checks run and any failures are resolved. Product gates and owner policy
approvals remain unchanged.
