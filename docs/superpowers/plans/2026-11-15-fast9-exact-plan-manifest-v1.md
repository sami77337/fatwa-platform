# FAST9 Exact Plan Manifest & Multipart Integrity v1

## Goal
Bind each approval receipt to the expected number and ordered identity of every plan part. Reject incomplete plans even if an attacker deletes both an intent and its unkeyed audit event and rebuilds the hash chain.

## Constraints
- Base: PR198 head 566afd081d4cd3db07455df1e718aaa17e2d4308.
- Branch: codex/20261115-fast9-plan-manifest-v1.
- Synthetic fixtures only. No send, network, production, merge or deployment.
- Preserve earlier branches and PRs.

## Implementation
1. Upgrade Outbox schema to v4.
2. Add expected_parts and canonical parts_manifest_sha256 to immutable approval claims.
3. Bind the manifest to ordered [ordinal, idempotency_key, action] entries.
4. Verify exact count, ordinal sequence, case, revision and approval fingerprint on every read.
5. Add a tamper test that removes an intent and matching audit event, rebuilds the unkeyed chain, restores schema triggers, and expects fail-closed rejection.
6. Document local threat-model limits and schema migration boundary.

## Acceptance
- Exact plan re-stage remains idempotent.
- Same receipt cannot authorize changed part manifest.
- Missing part is rejected even after audit chain rebuild.
- Existing crash, receipt, recovery, multipart and integrated tests pass.
