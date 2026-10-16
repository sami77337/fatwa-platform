# E1 verification record

Batch `20261017-wave6-functional-depth`; E1 only. Base
`b5de539237de0cd12b91b0705a3cb92014bfe98b`; head is the commit containing this
record (exact published SHA and CI links are recorded in the Draft PR/handoff).
All results below concern fabricated fixtures, not owner source acceptance.

## Bootstrap

Selected execution environment
`ccarenv_b64_Y2NhcmVudl9mMzRhYjdlMjM4YzA4MTkxODdlODNhYzA0MDdhZTgwMg`
became `ready`. Published flag, display name and standalone task URL/ID were not
exposed. Source delegation thread: `01a1173c-6c30-723a-828d-8948d842003d`.
Only this E1 worker was observed here; global lane concurrency/quota and usage
were not observed. No extra agents, hosts, credentials or security grants used.
[Bootstrap handoff](https://github.com/sami77337/fatwa-platform/issues/50#issuecomment-6226269189).

Actual runtime: `/usr/bin/python3.13` = Python 3.13.5; Node v24.19.0;
uv 0.12.23; cloud Linux. Bootstrap commands:

```sh
git fetch origin codex/20261017-wave5-review-worklist
git rev-parse FETCH_HEAD
git ls-remote --heads origin refs/heads/codex/20261017-wave6-e1
git branch --list codex/20261017-wave6-e1
git switch -c codex/20261017-wave6-e1 b5de539237de0cd12b91b0705a3cb92014bfe98b
uv --cache-dir /tmp/wave6-e1-uv-cache venv --python /usr/bin/python3.13 .venv
uv --cache-dir /tmp/wave6-e1-uv-cache pip install --python .venv/bin/python --index-url https://pypi.org/simple --no-deps -r requirements.txt
git push --dry-run origin HEAD:refs/heads/codex/20261017-wave6-e1
```

Both local/remote E1 branch lookups were empty before creation. Fetch returned
the exact base above. Eight existing exact requirements installed successfully
from PyPI; dependency files unchanged. Initial uv cache access to its default
read-only home directory failed; a writable disposable `/tmp` cache resolved
this without escalation. Push dry-run succeeded; actual push/PR evidence is
reported separately after publication.

## RED before fixes

Baseline owned suites: C1 11/11 PASS, D1 28/28 PASS.

New modules were run with:

```sh
.venv/bin/python -m unittest discover -s tests/content_intake -p test_exact_prepared.py -v
.venv/bin/python -m unittest discover -s tests/prepared_pipeline -p test_wave6_contract.py -v
```

Before implementation: the 16-method C1 regression run reported 21 assertion
failures (including subtests) and one JSON decoding error. D1's six-method run
reported two failures. Causes: trimmed question/title/notes/URLs; unbounded
input reads and rows; reference lists scanned before bounds; escaped surrogates
accepted in discarded fields; Unicode separators split a valid JSONL string.
The JSON decoding error was the reproduced JSONL separator defect, not missing
test setup. Existing passing mixed-batch/C2-contract assertions were retained
as compatibility evidence, not claimed as new fixes.

After that fix, a separately added numeric-overflow regression reproduced
`1e999` becoming infinity: C1 17 methods/two failing subtests; D1 seven
methods/one failure. Enforcing finite values in shared C1 JSON parsing fixed
both paths. D1 previously could return a report that `json_bytes()` could not
serialize. Final synthetic-example coverage was added afterward as executable
documentation of existing behavior.

## GREEN commands and counts

Executed from repository root with the isolated Python3.13 venv. No source
archive, catalog DB or media URL was opened. Separate commands count overlapping
tests again; totals must not be summed as unique coverage.

| Actual command | Result |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/content_intake -v` | 28 PASS, 0 fail/error/skip |
| `.venv/bin/python -m unittest discover -s tests/prepared_pipeline -v` | 36 PASS, 0 fail/error/skip |
| `.venv/bin/python -m unittest discover -s tests/fatwa_drafts -v` | 17 PASS, 0 fail/error/skip |
| `.venv/bin/python -m unittest discover -s tests/reference_links -v` | 37 PASS, 0 fail/error/skip; pure/mocked adapters only |
| `.venv/bin/python tools/dev/qa.py system` | PASS, Django 0 issues |
| `.venv/bin/python -m unittest discover -s tests/dev -p 'test_*.py' -v` | 42 collected: 40 PASS, 2 Windows-only skips, 0 fail/error |
| `.venv/bin/python tools/dev/wave3_qa.py --standalone --require-integrated` | PASS: 28 C1 + 17 C2 + 37 reference tests; no DB |
| `.venv/bin/python tools/dev/wave4_qa.py --wave3 --json /tmp/wave6-e1-wave4-summary.json` | PASS: all 11 required entries; see breakdown below |
| `.venv/bin/python tools/dev/qa.py node` | 94 collected: 85 PASS, 9 skips, 0 failures |
| `.venv/bin/python -m docs.dev.e1.synthetic_example` | PASS: seven report rows, three valid C2 drafts; hashes in README |
| `git diff --check` | PASS |

D6 breakdown: node version + Django check; D1 36; E2 baseline preview 16,
pipeline preview 9, worklist 19; D3 37; filter UI 4; D4 Node runner 26 PASS;
landing 18; nested C6 PASS (28 + 17 + 37). These are current baseline E2/E3
tests, not validation of other Wave6 lane changes. D6 disables DB access with
`PGPORT=1`. No actual DB tests were added to pure discovery.

Dispatcher skips: `test_cmd_unicode_checkout_and_nonzero_exit` (Windows CMD
only), `test_cmd_propagates_failure_unicode_path` (Windows CMD). Node skips:
one unavailable owner-archive identity check; seven Windows launcher/call
operator tests; one PowerShell parser test. This run did not execute historical
startup scripts or change execution/sandbox policy.

Precommit checks identify the base SHA with `working_tree=DIRTY`, as expected
while authoring. Publication is followed by a clean-commit C6/D6 verification;
the PR/handoff identifies that exact tested head. Machine output/logs reside in
disposable `/tmp/wave6-e1-*` files, not owner-data artifacts.

## Limits and integration dependencies

- Windows execution, B6 PostgreSQL 17/18, migrations and real browser acceptance:
  NOT_RUN by this E1 worker; coordinator/E5/E6 own the combined matrix.
- Full importer and real-source/source-browser acceptance: NOT_RUN here; no
  source archive or owner catalog was accessed/reimported.
- E2/E3 assembled Wave6 composition: NOT_RUN. The five-row fixture variant
  resolves on baseline D3. The full seven-row example reproduces baseline D3
  `ValueError: Duplicate external_id`; duplicate-row handling remains a
  coordinated E3/E2 dependency. No cross-lane patch was made.
- C1 candidate artifacts for invalid rows retain their established filtering
  contract; CLI export refuses an INVALID manifest. D1 receives the original
  canonical batch to retain every blocked row. See README eligibility table.
- Source pins and `test_identity` are caller assertions, never proof an archive
  was inspected. Mismatch does not mean verified evidence or scholarly approval.
- No shared-root dependency/route change is needed for this patch. C6/D6 already
  discover both new test modules through their owned directories.
- No independent review, product/source acceptance or next-wave authorization
  claimed. USAGE_NOT_OBSERVED. NOT_DEPLOYED / GATES_HOLD.
