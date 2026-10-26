# FAST8 offline acceptance evidence

Generate an actionable Arabic readiness matrix from the existing FAST6 composed
verifier. It executes `apps.fast6_journey.integration.run_integration`, which
already reuses source_readiness, policy_gap_engine, workflow_invariants and FAST6
journey services. There is no duplicate importer, workflow engine or policy engine.

From the repository root with existing Python 3.13 dependencies:

```console
python -B -m tools.fast8_acceptance_evidence --synthetic-fixtures-only
python -B -m unittest tests.fast8_acceptance_evidence.test_services tests.fast8_acceptance_evidence.test_cli -v
```

The CLI writes deterministic UTF-8 JSON bytes to stdout. `--verify-stdin` accepts
at most 1,000,001 bytes, rejects reports larger than 1,000,000 bytes, and checks
exact replay against the fixed services. It does not parse submitted reports as
authority, accept source paths, open owner archives, write files, connect to a DB,
run Git, or make network requests. Capture stdout as **binary bytes** for replay;
Windows PowerShell text redirection/pipelines may change encoding or line endings.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Matrix generated with successful synthetic service replay, or exact replay verified. Overall acceptance remains BLOCKED. |
| 1 | Matrix generated, but producer verification failed or its fixed input/adapter was unavailable. |
| 2 | Invalid invocation, production guard rejection, or submitted replay mismatch. |

`FATWA_PRODUCTION` must be unset or exactly `0`; production Django settings and
non-boolean service opt-in are rejected before fixture collection. CLI errors are
machine-readable and omit unknown argument values and exception details.

## Contract and provenance

`fatwa.fast8-acceptance-evidence.v1` contains a bounded matrix (maximum 40 rows),
actionable `requirement_ar`, expected artifact identifiers, dependencies, status
counts and JSON Pointers into a retained upstream artifact. The current healthy
fixture run contains 21 requirements: three synthetic PASS, four BLOCKED, six
NOT_RUN, six NOT_SUPPLIED and two NOT_CONNECTED. The complete fixed upstream
report preserves original source identities, Arabic Unicode, CRLF, timestamps,
source hashes, policy fixture provenance and unresolved joins.

`artifacts[0].sha256` hashes **exact upstream UTF-8 report bytes**, reproduced by
`apps.editorial_export.services.encode_json(artifacts[0].payload)`. Its `bytes`
field is the upstream byte length. Expected archive hashes are separately marked
`expected_only`; neither is an observed original-archive hash. The reviewed base
SHA is context (`92fa517ecdefe3f1a92a1ab145ff55943474df44`), not an observed
execution SHA. `execution_commit` remains NOT_SUPPLIED because the offline engine
does not inspect Git. Delivery verification records the actual committed SHA and
remote CI separately in the Draft PR.

Requirement identifiers belong to this FAST8 adapter; they are **not** invented
owner acceptance document IDs. Known ZIP basenames and expected hashes come from
AGENTS.md. Historical policy and transition counts and U03/U10 clause totals come
from policy_gap_engine evidence. No clause or historical record contents are
manufactured. No owner acceptance document is supplied or approved here.

## Status semantics and boundaries

| Status | Meaning in this matrix |
| --- | --- |
| PASS | Executed fixed synthetic verification succeeded. Never scholarly acceptance. |
| FAIL | An executed check or upstream contract failed. No partial green rows are emitted. |
| BLOCKED | Prerequisite acceptance/evidence is missing; official holds remain. |
| NOT_RUN | This offline command did not run HTTP, browser, PostgreSQL or remote CI. |
| NOT_SUPPLIED | Owner artifacts are absent from this adapter, or a fixed fixture could not be read. |
| NOT_CONNECTED | An upstream producer cannot be imported, or a required integration link remains unavailable. |

Both original owner ZIPs, the 70 historical permission rows, 58 historical
transitions and U03/U10 acceptance remain NOT_SUPPLIED. The synthetic policy
inventory (four actions and one transition) does not fill historical coverage.
Source readiness is BLOCKED with no observed source hashes. FAST6 still reports
`transcript_to_stock_queue` and `permission_to_case` as NOT_CONNECTED. Existing
connected bridges retain their actual provenance in the upstream report.

CI B6/C6/D6 are explicitly NOT_RUN in this offline matrix, even if an external CI
run is green. Attach actual workflow/run/job evidence and the execution commit
separately; this adapter offers no switch for asserting CI or owner approval.
Production and scholarly acceptance remain BLOCKED in every result.

No routes, migrations, writes, grants, approvals, AI services or deployment.
NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING.
