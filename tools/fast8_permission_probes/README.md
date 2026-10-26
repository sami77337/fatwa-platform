# FAST8 permission boundary probes

Standalone executable QA over the existing `permission_lab`, `policy_gap_engine`,
`workflow_invariants.replay` and pure `intake_workflow.check_intake` services.
No replacement policy engine, settings changes, application registration, routes,
database operations, migrations or network services.

From the repository root with the existing Python 3.13 environment:

```powershell
python -B -m tools.fast8_permission_probes --synthetic-only
python -B -m tools.fast8_permission_probes --synthetic-only --list
python -B -m tools.fast8_permission_probes --synthetic-only --scenario stale_case_key
python -B -m unittest tests.fast8_permission_probes.test_runner -v
git rev-parse HEAD
```

The CLI emits UTF-8 JSON to stdout, including observed results, required reason
codes, manifest SHA256, pinned inventory/source identity and source-preservation
evidence. The report's `reviewed_base_sha` identifies the reviewed FAST7 base,
**not the current tested commit**; record `git rev-parse HEAD` alongside a run.
`--list` emits the actual machine-readable regression definitions without running
them. No caller records, policies, paths or source archives are accepted.

Exit codes: **0** all selected scenarios passed; **1** regression or unexpected
probe exception; **2** CLI/manifest error; **3** trusted source baseline unavailable
and probes NOT_RUN. A single selected scenario is reported as one, not full coverage.
Source loss at final verification makes the report FAIL even if earlier probes passed.

## What the 27 scenarios check

- Exact impersonation labels, hidden/fullwidth characters, internal principals,
  actor/action/resource mismatches, candidate-only access and review targets.
- Invalid review transition and a valid transition that still grants no permission.
- Stale case key/state, different source/payload SHA, substituted source offset and
  reference identity: existing replay must reject without changing the snapshot.
- Duplicate external IDs: both fixed intake rows stay BLOCKED_INVALID with
  `duplicate_id`; substituting one row's identity into the other is rejected.
- All five pinned permission artifacts: syntax-preserving substituted bytes must
  cause source failure. Real evaluators/hash checks run; no fake decisions are injected.

Every hypothetical policy request must return actual DENY/false and its required
reason codes from **both** services. The exception is the permission lab's source
failure contract: it raises `SourceUnavailable`, which is reported as an exception
outcome with null effect/allowed, never manufactured as a lab Decision. The policy
gap engine must return its actual DENY decision in that same case.

Case identities are not resources supported by the permission lab. The report
explicitly marks the case-authorization adapter **NOT_CONNECTED**: policy probes
observe `UNKNOWN_RESOURCE`, and separate domain evidence verifies the existing
source-binding/replay rejection. Neither observation fabricates a case-to-role
mapping or claims integrated case authorization. Replay rejection is not a policy
decision; valid workflow compatibility is not permission.

## Isolation and bounds

Run this tool in its own CLI process, never in a live application or concurrently
with application threads. Source probes temporarily intercept reads of one exact
bundled path via `Path.open` and return altered bytes from memory. The context is
restored even on failure; no source file, source pin or authorization setting is
written. All remaining service behavior is real. Tests verify untouched bundle
bytes and catch deliberately removed pin checks, lost reason codes, unexpected
ALLOW and erroneous replay acceptance.

The fixed manifest is limited to 64 KiB and 64 scenarios; each replay uses one
event. No custom input option exists. Fixture identities are the vendored S3
synthetic inventory (source commit `88c411852d1a90e62ec71ab1c9ae2278f72d0c76`,
inventory SHA256 `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4`)
and fabricated Wave7 intake rows `intake-1`, `intake-4`, `intake-7`. The payload,
reference identities and original/substituted source hashes are reported at runtime.
Original Unicode, source bytes and slices are retained; no timestamps are generated.

## Integration and limits

No shared CI YAML was changed. The coordinator must explicitly add the new
unittest command and CLI command to integration CI; existing B6/C6/D6 runs alone
do not prove these new scenarios ran. The CLI has no browser surface; no browser
acceptance is claimed. PostgreSQL is not used or tested by these pure probes.
Only new and directly related tests are run locally.

Owner sources **NOT_SUPPLIED**; source acceptance **NOT_RUN**; historical policy
records and owner-approved case authorization remain unavailable. Synthetic PASS
does not advance any gate or grant any role.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.**
