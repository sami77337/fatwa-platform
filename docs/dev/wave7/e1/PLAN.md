# Wave7 E1 intake implementation plan

Goal: persist every accepted synthetic payload row/reference exactly once,
including blocked/scalar/null rows, under the approved guarded foundation.
Spec: accepted foundation `34355f5173667c6167351cf379ad56957d7f35f3`, frozen
contracts plus the dispatched approved LOSSLESS_NUMERIC_STORAGE override.
Execution: native work in the new Cloud worktree; no renewed foundation design,
schema change or approval round. Parent arranges combined independent review.

Architecture: pure `check_intake` parses source with the approved parser and
classifies validation-only projections with existing D1; authoritative source
is always `ParsedPayload.raw`/`SourceSlice`. `import_intake` calls the one shared
`synthetic_atomic` before reads/writes, performs fixed-scope key/SHA idempotency,
and uses one inner savepoint for a batch uniqueness race. All new references
start UNVERIFIED without identity/citation. CLI check stays pure; import delegates
to this guarded service and never seeds data within its transaction.

Owned files: `apps/intake_workflow/intake.py`,
`apps/intake_workflow/management/commands/wave7_intake.py`,
`tools/content_intake/cli.py`, `tests/intake_workflow/**`, this doc directory.
No shared model/migration/guard/settings/routes/dependency/CI changes.

1. [x] Write RED pure tests for exact slices/strings/huge numbers, malformed and
   duplicate rows, bounds, acknowledgement, fixed configuration and pure CLI.
2. [x] Write real TransactionTestCase RED tests for check/no writes, guard before
   atomic/write, replay/conflict, partial rollback, same/different-payload races,
   exact rows/pointers, and CLI check/import. Separate PG-only label.
3. [x] Implement the announced dataclasses/functions and bounded management/pure
   CLI adapters. Non-string numeric validation values are never cast to IDs or
   serialized as source; malformed pointers persist using original slices.
4. [x] Run pure + compatibility tests and own PG tests on new marked loopback
   PG17/18 databases. Preserve old lane resources/worktrees. Record actual
   versions/counts/commands. Windows is pending actual E5 CI wiring/run.
5. [ ] Commit/push coherent tested increment; one Draft PR targets
   `codex/20261017-wave7-e5-foundation`, never main. Report source/security/DB/
   independent-review limits and actual test labels to coordinator/E5.

Review focus: filtered source loss; numeric lexical underflow/rounding; invalid
IDs accidentally ready; idempotency conflict mutating children; uniqueness races
poisoning the outer transaction; command check accidentally initializing DB;
schema/ownership refusal occurring after a write; replay using a current parser
result instead of existing immutable batch metadata. These receive explicit tests.
