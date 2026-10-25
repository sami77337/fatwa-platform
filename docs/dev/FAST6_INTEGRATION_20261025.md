# FAST6 integration — synthetic development only

Base and Draft PR target: FAST5 #116,
`codex/20261025-fast5-integration-pc2`,
`0eef6b29943364dddae35a193b356ab79a2e2b5e`.
Branch: `codex/20261025-fast6-integration-pc2`.

## Source identity and execution

The worktree was clean at the exact base. GitHub PR metadata and `ls-remote`
matched all requested heads; all four are single children of the base and
`git cherry` marked all missing. Applied only these with `cherry-pick -x`:

| PR | Original SHA | Applied SHA |
| --- | --- | --- |
| #118 | 71777b5d3d6e69e0658c0a9e78a677c52fe7ad71 | 1546665695d8e58fae05348988cceb98a9d83e5f |
| #120 | b87c1657d450b325a34f62af9340e1871ee1758a | 3d5063c9317655a4839b19384cf09caaa84e16aa |
| #117 | dfe876c82c7d9bc5b52b63c5db9c9400ba285b84 | 560884d3dad094c03d93641e1f5509c183532e91 |
| #119 | 8d0f6ec6eaf2a18a58d73fc6e3de600504f4bc27 | 30016cd8f1fdf2038b9b7c19c9fcbaf92ce42bb1 |

No conflicts. All four stable patch IDs match their originals. Of 49 imported
files, 48 remain identical Git blobs; only the journey CLI receives the additive
`--integrated` switch. The original journey service/report is unchanged. Existing
Wave3/FAST1–FAST5 history remains in ancestry. The existing rehearsal loop is
extracted unchanged for reuse, with its original selectors and HTTP behavior
preserved. No settings, dependencies, migrations, protected fixtures or policies
are changed.

## Functional result and decisions

```text
python -B -m tools.fast6_journey --synthetic-fixtures-only --integrated
```

This executes all four FAST6 services and emits deterministic JSON to stdout.
The consolidated report contains 20 exact original export packets alongside
transient rehearsal projections, original packet hashes, complete source
identities, accepted/rejected attempts, workflow invariant replay, permission
gap diagnostics and owner-source readiness. `verify_integration` reruns services
and requires exact bytes, with a 2,000,000-byte input bound.

| Boundary | Integrated status | Evidence or blocker |
| --- | --- | --- |
| Prepared records → rehearsal | CONNECTED, offline only | 11 fixed prepared rows use the existing eight attempts and pure contracts; original batch/row/hash identity is checked. Missing drafts reject all attempts. |
| Rehearsal → consolidated export | CONNECTED, offline only | Each projection accompanies its exact original packet; stock export files are unchanged. No projected review is represented as persisted review or scholarly approval. |
| Transcript → fixed queue | NOT_CONNECTED | Transcript produces questions and preserved timestamp/source traces, but no draft: media/references are missing. The 20 queue cases come from independent fixed sources; no exact identity mapping exists. No inferred joins or fabricated media/references. |
| Permission resources → exact cases | NOT_CONNECTED | Resources are hypothetical labels/states with no case/batch/row/source identity contract. Adding a binding would invent one. All requests remain DENY_DEFAULT; U03/U10 and historical policy evidence remain absent. |

Ruling: keep bridges offline and additive instead of changing the fixed HTTP
queue, replay selector or stock export schema. This preserves original patches
and consumers while delivering safe pure bridges. It does not claim an end-user
browser connection for the prepared bridge. The unswitched journey deliberately
continues reporting the original four gaps; `--integrated` reports the two
remaining gaps in its distinct `fatwa.fast6-integration.v1` schema.

The invariant engine is executed against its original allowlisted scenario;
prepared rows use the existing rehearsal contracts, not an expanded event-log
command surface. Owner readiness reads inherited metadata only and remains
BLOCKED, with owner acceptance/raw evidence NOT_RUN. No 70 historical rows, 58
transitions, owner approvals, source evidence or scholarly decisions are created.

## Measured verification

Python 3.13.17 / Django 5.2.18 from the existing external environment
`C:/Users/S.AlAttar/.codex/tmp/fast3-venv/Scripts/python.exe`; Node 24;
real sandboxed Chrome 155.0.8059.85. No environment configuration was changed.
Initial evidence is at applied HEAD `30016cd` plus integration working changes;
final-head CI evidence belongs in the Draft PR, not inferred from source CI.

- Four source suites together: 100 tests, 99 passed, one Windows symlink skip.
- Combined FAST6 plus directly affected suites: 209 tests, 208 passed, one skip,
  86.214 seconds. The skip is the source CLI symlink test: Windows privilege
  error 1314. No owner-source or PostgreSQL acceptance is claimed.
- Real Chrome: three tests passed, 18.917 seconds (FAST6 journey, FAST5 shared
  navigation, original rehearsal). RTL/keyboard at 1280/375/320px, exact Arabic,
  CRLF/combining marks, closed unverified references and read-only local requests.
  FAST5: 159 requests; rehearsal: 114; zero runtime/network/HTTP errors or policy
  violations. Research uses an explicitly injected synthetic catalog and checks
  edition-scoped hrefs; it does not claim a populated local PostgreSQL catalog.
- Offline CLI: workflow, permission gaps, original and integrated journey passed;
  generated synthetic source readiness passed. `--pinned-owner` returned expected
  BLOCKED/exit 2 and no observed raw hashes.
- Django system check, scoped Ruff lint/format and `git diff --check` passed.
- Red/green: integrated CLI first failed as an unsupported option; exact export
  substitution first escaped verification, then was rejected after adding full
  export replay and original-packet comparison. Strict output validation exposed
  domain enums; the adapter now uses the components' existing JSON serialization
  rather than relaxing bounds or types.
- A first directory-label test invocation failed collection because `tests` is a
  namespace package. Explicit module labels fixed collection; no test was dropped.

Reproduce the affected suites (PowerShell; substitute the Python executable):

```powershell
$dirs = 'workflow_invariants','policy_gap_engine','source_readiness','fast6_journey','workflow_rehearsal','permission_lab','research_bridge','editorial_export'
$labels = $dirs | ForEach-Object { Get-ChildItem "tests/$_" -Filter test_*.py -File } | Where-Object Name -ne 'test_browser.py' | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\','.').Replace('.py','') }
python -B manage.py test @labels tests.integration.test_fast4 tests.integration.test_fast5 tests.editorial_workbench.test_batches tests.wave7_foundation.test_contracts --settings=config.settings.test --noinput --verbosity=2
python -B manage.py test tests.fast6_journey.test_browser tests.acceptance.fast5.test_browser tests.workflow_rehearsal.test_browser --settings=config.settings.test --noinput
```

CI adds explicit FAST6 module selection to the existing C6 Windows/Linux jobs,
including the new bridge tests and affected rehearsal/export/FAST5 tests. D6 adds
one real Chrome journey invocation only on its existing Linux job, with executable
preflight. No new jobs/matrices, removed guards, broadened timeouts or weakened tests.
B6 is unchanged.

| Actual fixture/report | SHA256 |
| --- | --- |
| Transcript fixture `tools/transcript_pipeline/examples/synthetic-manual.json` | e217c93eac5fa0109e3c4134b478ce3e6500e8723692312a6c14194ccece40ee |
| Generated synthetic source input | 2f86499955ef4cf44c22f508cc2ffa1ebe352047cd40414e981d896a29b83a0a |
| Generated synthetic ZIP (local run) | 2b05c52e10cb81bb3b182d67d82c0749df8f6917dada82eef6b2d1b64e423bde |
| Original journey report | 82ff4bc88bf1b1f126a2b69bd9b15259e6b818b706b18e405cb8362e0473018e |
| Integrated report, 282,974 bytes | 1f398dc8820159559f5afafee3054d592e2e5ac02992e7e9461c82ae582a97e5 |
| Permission gap CLI report | 65a0bb9484a6eff314447e1d8966bc1c5401dff626068eaa32c77e5b1e400f90 |

Logs/reports are in ignored `.local/qa/fast6/`. Report output files are explicit
test artifacts; production services perform no file writes, DB, socket or subprocess
operations, verified with the real integrated service under side-effect guards.

No migration or data conversion. Rollback is code-only. No private records,
publication, grants, deployment, main merge, or changes to official gates.
One independent final read-only review is required before pushing; its outcome
and final exact-head B6/C6/D6 status are recorded in the Draft PR.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED / GATES_HOLD.**
