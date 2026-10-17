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
