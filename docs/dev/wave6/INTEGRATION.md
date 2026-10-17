# Wave6 development integration candidate

Base: `codex/20261017-wave5-review-worklist` at
`b5de539237de0cd12b91b0705a3cb92014bfe98b`.
Candidate: `codex/20261017-wave6-integrated-candidate`.

All six exact accepted lane heads are preserved as merge ancestors. Producer
branches and commits are untouched; merges had no conflicts. This candidate
is for combined verification and fresh independent review only. It does not
claim combined acceptance or authorize Wave7.

| Lane | Draft PR | Pinned ancestor |
| --- | --- | --- |
| E1 | [#54](https://github.com/sami77337/fatwa-platform/pull/54) | `c38c7ed6b120de07730cb34a51678f6929305249` |
| E2 | [#51](https://github.com/sami77337/fatwa-platform/pull/51) | `b1289215a8cc83a20a70caed553bf664dea7be40` |
| E3 | [#53](https://github.com/sami77337/fatwa-platform/pull/53) | `26dba43149129e3f0cbd5689247cc3da9fe5d3c2` |
| E4 | [#55](https://github.com/sami77337/fatwa-platform/pull/55) | `cdbe818e464d1b27d821f620b749c9e526524f19` |
| E5 | [#56](https://github.com/sami77337/fatwa-platform/pull/56) | `79149964da658c3f9192ab1c1512016ccf950aa4` |
| E6 | [#52](https://github.com/sami77337/fatwa-platform/pull/52) | `a541cd9b3693e034173242f44fdb33dbb7358e2b` |

## Integration wiring

The three patches in `docs/dev/e5/INTEGRATION_HANDOFF.md` were applied once,
in order, after all actual lane files existed. The corrected E4 head retains
its no-DB `test_e4_catalog` label. Corrected E6 requires service, assets,
review-batches, regressions, and real browser with the tenth review-batches
journey. Missing/zero suites remain failures. E3 DB tests are only in B6 and
qa_worker, outside port-1 C6/D6. The E5 patch includes explicit Node24 setup for B6 PostgreSQL jobs.
All three workflows now check out the exact PR head (or push SHA), rather than
the temporary PR merge commit, so reported test SHAs identify the candidate.
The initial run checked merge5c82fe5b1252fd71a687fa1ad6d8309d57e097a0,
whose tree exactly equals head6424e52e6e0e80781e84392b1545d38e7f1729fd.
Removed a redundant second Node setup added during initial integration.

Integration changes: `.github/workflows/b6-integration.yml`,
`.github/workflows/c6-wave3.yml`, `.github/workflows/d6-wave4.yml`,
`tools/dev/qa.py`, `tools/dev/qa_worker.py`, `tools/dev/wave4_suites.json`,
and this record. No producer implementation or contracts changed.

## Verification status at initial publication

Python3.13.5 venv created by uv from `/usr/bin/python3.13`; all eight exact
requirements pins installed. Node24.19.0. Git remote verified.
Initial combined D6 `python tools/dev/wave4_qa.py --wave3 --reports
.local/qa/integration/d6 --json .local/qa/integration/wave4-summary.json`
passed with the integration wiring uncommitted: D1 37; D2 16+9+19+11+6;
D3 50; D4 Django4+8 and Node49; D5 18. Nested C6 intake30,drafts17,links50,
importer84 (80 pass,4 source skips,7 modules,zero uncollected). These
prepublication results are not exact final-head CI evidence. Final evidence
will be attached to the same Draft PR after committed-head CI completes.

Combined B6 PG17/18, Ubuntu/Windows C6/D6 and actual protected desktop/mobile
browser are pending at initial publication. No local cloud browser bypass
will be attempted. Source-specific acceptance NOT_RUN: trusted owner source
not available; all four importer source skips remain disclosed.

No source imports, owner DB access, real fatwa drafting/publishing, main merge,
deployment, credentials, grants or security changes. Source pins are caller
assertions, not archive-inspection proof. Gate B NOT_PASSED; C/D/E HOLD;
Phase01 BLOCKED. NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.

## First combined runtime findings

Initial B6 run38984354783 on PR merge5c82fe5 (tree identical to head6424e52)
ran PG17 and18:158 B6 cases each, including the 12 real E3 adapter cases.
E6 guard6,transport6,service8,assets2,regression1 passed. Actual Google Chrome
155.0.8059.39 started with its sandbox enabled. Browser10 journeys:7 PASS,
3 FAIL,0 NOT_RUN. Review-batches HTTP3:2 PASS,1 ERROR (`StopIteration`).
Artifacts12082177646(PG18),12081459876(PG17) contain screenshots and traces.
The connector downloaded an archive reference, but workspace retrieval returned
HTTP403; raw job logs were inspected successfully. No artifact content is
claimed inspected from that failed retrieval.

Recoverable E6 integration assumptions are corrected only on this candidate,
never on the E6 or E2 producer branches: actual E2 list links use trusted
batch-local `row` ordinals, not legacy `/SYN-ID` paths. HTTP and real-browser
assertions now follow row3 and verify SYN-M03; the old path wait for row2 and
repeated row1 is updated likewise. E2 behavior and its contract are unchanged.
The first real browser also exposed Enter not submitting the native review
form; the CDP Enter key now supplies its carriage-return text. All existing
keyboard, filter, batch and return assertions remain required. These runtime
fixes require the next protected CI run to establish GREEN. Added bounded
synthetic failure diagnostics and final browser metadata to CI logs, alongside
unchanged screenshots/trace artifacts, to investigate the catalog reload
failure rather than guessing a production change. No catalog code changed.

Additional candidate paths: `tests/acceptance/wave6/test_review_batches.py`,
`tests/acceptance/wave6/review_batches.mjs`, `tests/acceptance/wave6/browser.mjs`.
The full10 browser journeys, including review-batches, remain mandatory.

Second protected run38984629868 tested exact head47cfeda8291fc0ef26d90419ae9ee6166bfdf2c8
on both PG versions: review-batches3/3 and browser9/10 passed, proving row-link
and Enter corrections. The one remaining failure was a test expectation:
`docs/dev/e4/README.md` explicitly requires search/filter reloads to render
native SSR fallback pages (also present in the pinned base). Diagnostic actual
DOM had the correct20 results, exact query/depth/children/root/page and no
interactive panel. The browser journey now requires that native SSR state,
checks result21 on page2, follows actual native detail/return and clear links,
and separately re-enters the interactive page to verify JavaScript clear and
PR47 basic-link state. No assertion is optional; no production change made.
Both native and enhanced navigation remain exercised in the same mandatory
journey. Third protected run must establish the final10/10 result.

The exact compact1,000,000-byte E1/E2/E3 probe also passed on the assembled
candidate:800 rows,original whitespace unchanged,D3 received1,000,000 bytes,
zero fabricated drafts/references.1,000,001 bytes rejected. This supplements
the committed1MB/row/reference and999,999-byte regressions; it is a one-off
runtime probe, not a new counted unittest method.

## Independent combined review P2: D1 optional source-pin comparison

Fresh independent Astra review of head921ac85702ffe1a02892fcb1e96a63cf886a592f
returned FIXES_REQUIRED for one integration contract defect. E3 now exposes
explicit edition_key/archive SHA in Heading evidence, while D1 compared only
namespace/book/input SHA. Actual wrong edition/archive evidence could therefore
remain D1 verified although D3 rejects it and E2 suppresses its citation.

RED before the production edit, Python3.13.5 uv environment:
- `PGPORT=1 /tmp/wave6-venv/bin/python -m unittest discover -s tests/prepared_pipeline -p test_source_pins.py -v`:4 methods,2FAIL/2PASS. Both mismatches returned verified instead of mismatched.
- Disposable synthetic PG18 container fatwa-wave6-p2-20261017-pg18,loopback
  port32768,base/test names wave6_p2_ephemeral/test_wave6_p2_ephemeral;
  `manage.py test` with the four new `CatalogAdapterTests.test_pipeline_actual_adapter_*`
  labels,`--noinput --verbosity=2 --settings=config.settings.test`:4 methods,
  2FAIL/2PASS for the same explicit-pin mismatches. Matching and legacy optional
  metadata compatibility passed. Fixtures only; no owner source/database access.

The narrow D1 correction compares available edition_key and archive SHA exactly
against ExplicitMapping.c2,using the same per-field None compatibility as D3.
No inferred identity,casting,global cache or D3 change. None means optional
metadata absent; available metadata must match. Existing resolver validation
continues rejecting malformed explicit values. D1's documented intake-readiness
status is independent of reference verification and remains unchanged: mismatches
are `mismatched` plus `references-unverified`; E2 requires human review and
suppresses citations. Original strings and in-memory receipt semantics survive.

GREEN local:all41 prepared_pipeline methods and all16 actual PG adapter methods
PASS,0fail/error/skip. The four new DB methods compare D1/D3/E2 behavior using
DjangoCatalog and assert SELECT-only reads; legacy compatibility deliberately
projects optional metadata away from actual adapter evidence (database edition
metadata itself remains explicit). The four new pure methods cover both
mismatches,matching pins,and each/both optional fields absent.

Mandatory wiring uses existing discovery:tests/prepared_pipeline automatically
joins D6 on both systems;the four DB methods join the already required nonzero
`tests.reference_links_db.test_catalog_adapter` B6/qa_worker label on PG17/18.
No DB module enters port-1 C6/D6 and no optional fallback is added.

New integration-correction paths:apps/prepared_pipeline/__init__.py,
tests/prepared_pipeline/test_source_pins.py,
tests/reference_links_db/test_catalog_adapter.py,and this record.
All producer branch heads and six merge ancestors remain pinned. Full exact-head
CI,importer and protected10-journey browser must run again;fresh independent
same-head re-review stays pending. No acceptance or Wave7 dispatch.
