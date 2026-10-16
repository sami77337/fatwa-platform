# E2 independent-review fixes (same PR51)

This increment addresses FIXES_REQUIRED on initial E2 head
`feb70f0fe9d0fe71765044045bc5924aa175f676`. The development base remains
`b5de539237de0cd12b91b0705a3cb92014bfe98b`. The original commit is preserved;
publication is a normal additional commit on `codex/20261017-wave6-e2`, not a
force push. The PR/handoff supplies the final immutable SHA.

## Changes and observed regressions

1. E2 built a full-map scan for each reference's evidence check. The new
   composition builds one local exact `(c1_source_id, c1_heading_id)` index.
   Original-pointer equality, six-field C2 identity, numeric IDs and complete
   provenance equality are unchanged. There is no global cache.
2. Worklist links used original opaque external IDs as URL path segments. A
   synthetic `BLOCKED/UNSEEN` with null question stayed blocked in composition
   but list rendering raised NoReverseMatch. Duplicate IDs had ambiguous 404
   detail links; rows without IDs had no link. Every list row now links to the
   existing list route with an allowlisted batch and its stable 1-based input
   ordinal in `row=...`. Ordinals are assigned **before** filters/pagination.
   Return links omit only the row selector and retain filter/page/batch state.
   Legacy unique-ID detail URLs still work. Invalid/duplicate/conflicting row
   parameters reject before processing; absent ordinals return 404. No shared
   route, payload, persistence or arbitrary path was added.
3. Default JSON separators expanded a 999,999-byte accepted synthetic envelope
   beyond the new D3 1,000,000-byte limit. E2 now uses compact UTF-8 serialization
   and checks the final byte bound before D3. No input limit was increased.
4. Base D1 accepts some control-containing external IDs that D3 rejects. E2 now
   excludes those rows from D3 without changing IDs or losing valid siblings.
   D1-blocked rows remain blocked with no draft/citation. If the base D1 produced
   a receipt, E2 truthfully retains that receipt flag but requires review and
   suppresses citations. The coordinated E1 control-ID rejection takes precedence
   once assembled. Neither path invents IDs, source evidence, answers or approval.

The reviewer findings were independently reproduced in this task before edits:
NoReverseMatch, D3-size rejection, tab/newline/DEL exact-text rejection, and a
non-timing scan regression with 419,810 source-ID field reads for 20 references
against 20,000 mappings. It now performs 40,000 reads (one index in D3, one in E2).
The first scan-test instrumentation tried constructing another HeadingMap while
its slot was instrumented; that test setup error was corrected before the
419,810-read RED run. The regression subsequently passed unchanged.

## Actual commands and results

Use `/tmp/fatwa-e2-venv/bin/python`, which points to `/usr/bin/python3.13` 3.13.5;
Node is 24.19.0. Existing pinned dependencies were reused; no new dependencies.

```sh
PGPORT=1 /tmp/fatwa-e2-venv/bin/python manage.py test tests.editorial_demo.test_preview tests.editorial_demo.test_pipeline_preview tests.editorial_demo.test_worklist tests.editorial_demo.test_synthetic_batch tests.editorial_demo.test_review_fixes --noinput --settings=config.settings.test
/tmp/fatwa-e2-venv/bin/python tools/dev/wave4_qa.py --wave3 --json /tmp/e2-review-wave4-summary.json
git diff --check
```

- Editorial: **61 passed, 0 failures/errors/skips** (44 original + 11 first
  increment + 6 review-regression methods). The ID regression has tab/newline/DEL
  subcases and verifies behavior against D1's actual blocked/receipt result.
- Unchanged D6+C6: **PASS**; D1 28, D2 16+9+19, D3 37, D4 4 Django + 26 Node,
  D5 18, nested C6 11+17+37. Counts overlap. D6 does not yet discover either new
  E2 module, so the five explicit labels above are required.
- Diff whitespace check: PASS.

Reproducible benchmark (synthetic, no real-source performance extrapolation):

```sh
/tmp/fatwa-e2-venv/bin/python - <<'PY'
from time import perf_counter
from tests.editorial_demo.test_review_fixes import mapped_batch
from apps.editorial_demo.integration import compose_synthetic_batch
raw, mapping, bridge, catalog = mapped_batch()
print(len(raw), len(bridge.headings))
for run in range(2):
    start = perf_counter()
    rows = compose_synthetic_batch(raw, synthetic_fixtures_only=True,
        reference_map=mapping, bridge_config=bridge, catalog=catalog)
    print(perf_counter() - start, sum(r.status == 'verified' for row in rows for r in row.references))
PY
```

This task's fixture is **80,717 bytes**, 20,000 mappings, 20 rows x 100 distinct
references. On the same host, before: **3.433988s / 3.507132s**; after:
**0.146345s / 0.114225s**. All runs produced 2,000 verified references. This is a
separate fixture from the reviewer's 96,997-byte example. The regression test uses
field-read counts, not a fragile timing threshold.

## E1/E3 compatibility evidence and dependencies

A disposable **file snapshot**, not a published integration branch, combines
this E2 increment with E1 `44209c174d6625fa1f8254a7a0fdca3166e75145` and E3
`26dba43149129e3f0cbd5689247cc3da9fe5d3c2`. It lives under the path retained in
`/tmp/e2-composite-path.txt`. No other lane's files were edited in the E2 checkout.
Five explicit editorial labels passed **61/61**, including the near-limit test
against E3's actual new bound. Separate discovery: E1 intake **28 passed**, E1
pipeline **36 passed**, E3 pure **50 passed**, no skips. Initially the disposable
copy omitted E1's docs-based synthetic example and that pipeline test raised
FileNotFoundError; overlaying the exact committed E1 docs resolved setup and the
full 36-test rerun passed.

E1's published `docs/dev/e1/synthetic_example.py` also ran through actual E2
composition with E3: 7 original questions preserved byte-for-string, 3 blocked
rows retained, 1 verified citation, mismatched-source citation suppressed.

The parent separately coordinates E1's pending stricter control-ID fix. E2's
regression honors D1's actual blocked result and keeps a defensive isolation path
for the pinned base. A coordinator-assembled committed SHA, updated E1 control-ID
head and fresh independent review are still required; the disposable check does
not claim those approvals or final combined acceptance.

E5 must require **both** no-DB labels:
`tests.editorial_demo.test_synthetic_batch` (11 methods) and
`tests.editorial_demo.test_review_fixes` (6 methods), alongside the original three.
E6: new generated row links use `/dev/editorial-preview/pipeline?batch=...&row=N`
with other query state; existing `/pipeline/SYN-P01` unique-ID links remain valid.

No database or browser was used in these local checks. PostgreSQL/Windows CI on
the new head will be reported separately after publication; prior-head green CI
is not new-head proof. Real-source acceptance and final assembled browser remain
NOT_RUN. No deployment/merge/security setting change or source operation.
Independent re-review pending. NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.
