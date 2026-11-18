# P1 evidence addition — 2026-11-18

Reviewed product head: **`0055a5ab05c6dbe6d41a528666666f9db07f2fee`**, branch
`codex/20261117-v12-integration`, [Draft PR #231](https://github.com/sami77337/fatwa-platform/pull/231).
The P0 matrix baseline `cd8ecfd8b78de3884f7f54226385f228f817fdac` was already integrated
as `d15c54a`; this update is an additional commit only. No product file is changed.

## Observed remote evidence

Authenticated commit-workflow lookup returned **22 completed / 22 success** for
this head (first page, pull-request-triggered runs only). For
[run 44208238581](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581),
we read both actual jobs, their steps and decoded logs, rather than treating the
parent's report or a test's existence as execution proof:

| Job | Version printed in log | P1 affected | P0 functional/security | Other P0 batches | Scope baseline | Browser/recovery |
|---|---|---|---|---|---|---|
| [134479648225](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581/job/134479648225) | PG17.12 | 54 PASS, 20.333s | 183 PASS, 53.372s | 8 strict + 16 V11 + 22 compatibility PASS | 6 PASS | 1 PASS, 91.697s |
| [134479647759](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581/job/134479647759) | PG18.7 | 54 PASS, 33.920s | 183 PASS, 82.635s | 8 strict + 16 V11 + 22 compatibility PASS | 6 PASS | 1 PASS, 115.158s |

The logs show `TESTED_SHA=0055a5ab05c6dbe6d41a528666666f9db07f2fee`,
`FATWA_BROWSER_SANDBOX: 1`, successful system/drift stages and browser exit zero.
The pinned workflow uses `/usr/bin/google-chrome`; the pinned source and restored
browser harnesses pass that sandbox selection to Chromium. Each linked P1 test
method has an explicit `... ok` line on **both majors**; the validator checks those
lines and rejects a mismatched SHA or a missing pass in either job.

Counts are batches, not unique features. P0/P1 batches overlap; the two PostgreSQL
majors are repeated checks, not twice as many functions. The six scope tests in
this CI are the **old baseline validator**, not the nine local tests of this new
update. Final CI for the updated matrix belongs to the integrator.

We imported only relevant timestamped log excerpts, not whole logs or private
runtime inputs. `p1_manifest.json` hashes these extraction files, not the original
CI ZIP. Browser `result.json` and `restored-http.json` artifacts were not downloaded;
we do not assign a CI browser version or an exact HTTP count from the earlier
local receipt. The passing test was inspected: it requires a fresh second PG
server, a separate HTTP process, target database/server/private-root checks per
request, exact PNG/PDF/WAV bytes, current answer, outsider/scope/rights denials,
wrong-key/hash/ciphertext rejection before target creation, preserved partial
delivery and an unchanged frozen source. These concrete assertions plus the
exact-head passing log support the bounded journey claim.

## What changed in the matrix

Five explicit additions cover **91 original owner points**, keeping all source
texts, scope decisions, P0 evidence groups and classifications unchanged:

| Evidence group | Bounded addition | Still open |
|---|---|---|
| `p1-case-journey` | Canonical evidence/media chronology and same-case native navigation | Full assignment workflows, production identity and every device |
| `p1-multipart-edit` | Native text revision retains original parts/history and needs fresh review; malformed file/CSRF/stale cases denied | Recording microphone audio and every composer/media capability |
| `p1-rights-inspector` | Source/edition/position/pins and predecessor comparison; current versus historical rights; unsupported full text/quote/publication denied | Real licenses, full corpus, Quran/hadith source supply and all export paths |
| `p1-library-roundtrip` | Current-rights metadata search/facets/count/pages and native return context without granting authority | Semantic search, complete knowledge graph and production publication |
| `p1-browser-restored` | Connected synthetic journey and encrypted independent-target recovery in protected Chrome on both majors | Production PITR/KMS, actual providers, real data or acceptance |

[Exact source/test lines and SHA pins](EVIDENCE.md#p1-case-journey) are generated
from `git show` at P1; older evidence retains P0 pins. `extends_evidence_ids` adds
support and `supersedes_evidence_ids=[]` explicitly preserves history.
`evidence_sha` in each row remains the original P0 baseline; use `evidence_shas`
and `p1_evidence_ids` for actual multi-head attribution. `assessed_p1` is true only
for those 91 rows. No full requirement has been reclassified as complete.

The journey deliberately preserves `DELIVERED`, `FAILED_REQUIRES_REVIEW` and
`SENT_UNCONFIRMED` parts. It is not complete delivery, reading, external sending or
authority to restart a sender after restore. The library remains experimental;
rights inspection remains a VIEW operation, not permission to open or publish.

## Local checks and preserved limits

- `build.py --check`, `validate.py`: PASS; deterministic rendering, source hashes,
  both-head anchors, no status upgrade, and P0 preservation.
- Focused documentary tests: **9/9 PASS**, 2.810s. Added negatives reject wrong-head
  attribution and a missing P1 test pass on one major; a preservation check compares
  source fields/classifications and original P0 groups with the baseline embedded
  in the reviewed P1 commit.
- Ruff check/format and staged whitespace checks: PASS after one import-order fix.
- Product/PostgreSQL/browser tests were **not rerun** by P2. No app or integrator
  document edited. Earlier product/CI failures remain in the pinned
  [integration history](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/docs/product/V12_P1_INTEGRATION.md).

Original XLSX bytes remain unavailable; full extracted text and its own hashes
are retained. Main protection remains UNKNOWN after Forbidden, recommendations
only; no new read claim or settings change. U03, Meta contracts and real sources
remain unresolved. Reference **79% ±8** unchanged. **Gate B NOT_PASSED / C-D-E HOLD /
Phase01 BLOCKED / NOT_DEPLOYED**. No acceptance or deployment authorization.
