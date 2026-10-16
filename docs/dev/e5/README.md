# E5: complete importer collection and CI evidence

Batch: `20261017-wave6-functional-depth`. E5 owns this increment only.
Base: `b5de539237de0cd12b91b0705a3cb92014bfe98b` on
`codex/20261017-wave5-review-worklist`. Head: see the PR and commit ancestry;
reports record the actual executing SHA and working-tree state.

## Inventory at the pinned base

| Importer module | Cases | Source skips |
| --- | ---: | ---: |
| `test_book622_verification.py` | 7 | 1 |
| `test_catalog_audit.py` | 12 | 0 |
| `test_citation_audit.py` | 4 | 0 |
| `test_ingest.py` | 42 | 0 |
| `test_owner_adapter.py` | 14 | 0 |
| `test_owner_source.py` | 3 | 3 |
| Total | 82 | 4 |

The direct baseline command collected every one of these modules: 78 passed,
zero failed, four skipped. Baseline B6 runs Django labels and Node/tooling;
C6 discovers only content_intake/fatwa_drafts/reference_links; D6 adds
prepared_pipeline, editorial, filter UI and landing plus C6. Thus **none** of
those entrypoints ran these six importer modules before E5.

This increment adds `test_fixture_bytes.py` (two cases), making seven modules,
84 collected, 80 passed and four source skips on the tested Linux checkout.
The inventory regression pins these seven expected modules. New test modules
must update the reviewed inventory; deleting a module must not silently shrink it.

## Reproduced defect and repair

A disposable Git repository containing the exact synthetic fixture was staged
with `core.autocrlf=false` and checked out with `core.autocrlf=true`. Before the
repair, its SHA changed from the unchanged golden
`fa37b33efc506f3deb9f8d2f32223ef8bce85c9748fb840061b359437b3c94d3`
to `8bf1e991f08a366920b318a44921f53fc2a38f1017f5911420530dfa09506429`.
The regression failed on this equality before calling the importer. The fixture
folder's `.gitattributes` now marks its JSON data `-text`, preserving exact
committed bytes on Windows without changing the golden file, manifest or hash.
The same test now passes and performs actual synthetic ingestion after checkout.

Disposable LF/CRLF and BOM variants all parse when their *synthetic caller*
manifest pins the exact variant bytes. Reusing the original manifest with changed
bytes correctly rejects them. This was already correct importer behavior: no
normalization, golden-hash update or importer relaxation was introduced.

## Collection and evidence behavior

`wave3_discover.py` preserves stdlib unittest discovery and additionally compares
all expected `test*.py` files under its start directory with actual cases.
An empty module alongside a passing module fails. A namespace subdirectory that
stdlib discovery misses is reported as uncollected and fails. Import errors fail.
All three paths have subprocess regression evidence. The utility deliberately
does not silently hide or invent tests in uncollected directories; existing D6
per-directory discovery continues to run each leaf separately.

Optional `--json PATH` retains counts, per-module case counts, bounded skip IDs
and reasons (100 entries, 240 characters each), exact HEAD, working-tree state,
Python version and source/gate limitations. Plain CLI output retains unittest
failures. Module inventory is limited to 1,000 files. Report-write failures fail.
D6 records HEAD/working-tree state and Django case totals, and now rejects an
exit-zero Django test command reporting zero or no case total. This guard was
observed RED with zero tests, then GREEN with zero and one-case subprocesses.

C6 requires the full importer package on Ubuntu and Windows with Python 3.13 and
Node 24. D6's existing `--wave3` includes it too. C6/D6 upload collection JSON;
B6 uploads the exact executing SHA and verbose synthetic PostgreSQL test log.
Missing artifact files fail upload. Existing credential sanitization/port 1
remains unchanged for C6/D6, and no PostgreSQL tests were added there.

Commands from checkout root (the uv venv uses `/usr/bin/python3.13`):

```text
uv --cache-dir /tmp/fatwa-e5-uv-cache venv --python /usr/bin/python3.13 .venv
uv --cache-dir /tmp/fatwa-e5-uv-cache pip install --python .venv/bin/python --index-url https://pypi.org/simple -r requirements.txt
.venv/bin/python -B -m unittest discover -s tests/fiqh_import -v
.venv/bin/python -B -m unittest discover -s tests/dev -p 'test_*.py' -v
.venv/bin/python tools/dev/qa.py system
.venv/bin/python tools/dev/qa.py node
.venv/bin/python tools/dev/wave3_qa.py --standalone --require-integrated --reports .local/qa/c6
.venv/bin/python tools/dev/wave4_qa.py --wave3 --reports .local/qa/d6 --json .local/qa/wave4-summary.json
```

Raw logs remain temporary/private. Sanitized final SHA-specific evidence is
attached to the PR handoff. CI tests its actual checkout SHA (PR merge SHA when
applicable); do not equate that with the branch head without checking it.

See [integration handoff](INTEGRATION_HANDOFF.md) for pending actual lane files.
No independent review or owner/source/product acceptance is claimed.
`USAGE_NOT_OBSERVED / NOT_DEPLOYED / GATES_HOLD`.
