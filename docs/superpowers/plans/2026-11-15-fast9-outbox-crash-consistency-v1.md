# FAST9 Outbox Crash Consistency & Race Safety v1

## Goal
Prove SQLite transaction rollback across injected crash points and race safety between late verified provider receipts and expired-reservation quarantine.

## Constraints
- Base: PR197 head fc1c47f2c9a9aa327648dd32636492bf4aa76650.
- Branch: codex/20261115-fast9-crash-consistency-v1.
- Synthetic fixtures only. No sender, network, production data, merge or deployment.
- Preserve prior branches and PRs.

## Implementation
1. Inject failure after staging claim/part writes but before audit completion; retry and assert one complete clean plan.
2. Inject failure after provider receipt insert and intent update but before audit append; assert all writes rolled back and exact retry succeeds.
3. Race expired-reservation quarantine against a late verified DELIVERED receipt; assert final part remains DELIVERED regardless of winner.
4. Assert plan-level summary remains partial while other parts are pending.
5. Add suite to FAST9 integrated CI and document guarantees/limits.

## Acceptance
- No orphan approval claim or partial plan after failed stage transaction.
- No provider receipt row or state transition survives failed audit transaction.
- Late verified delivery wins over or follows quarantine without losing terminal evidence.
- Both race orders preserve a DELIVERED final state.
