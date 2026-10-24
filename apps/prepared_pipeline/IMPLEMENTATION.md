# Synthetic prepared-input build

The owner authorizes autonomous execution, independent implementation and one final
review. This plan stays inside the intake lane; historical branch/lane rules yield
to the current assigned worktree and ownership. Base starts at
`293cfebccb18e0231926dedfb920f8163d9ab624`.

## Design and implementation plan

Reuse C1 format adapters and C2 receipt creation instead of introducing a second
schema or persistent staging layer. Keep `prepare_batch` strict and compatible;
add `prepare_file` for direct CSV/JSON/JSONL processing without dropping rejected
rows. Keep trusted mappings/catalogs as explicit caller dependencies.

- [x] Improve C1 independent field validation, symmetric duplicates, CSV cell
  errors and existing C2 text bounds (delegated adapter implementation).
- [x] Add direct file preparation, complete per-field errors and per-reference
  locations; provide deterministic workbench summaries and rejection reasons.
- [x] Add bounded multiple-batch processing, cross-batch duplicate rejection and
  an offline CLI (delegated collection implementation).
- [x] Run new and affected pure/Django consumer tests, one independent review,
  and address material findings. Delivery: commit/push and create one draft PR.

Write behavioral regressions and observe failures before each implementation.
Review focus: mixed rejected/accepted rows, exact Arabic/CRLF/RTL preservation,
duplicate identities across files, mapping aliases, malformed input isolation,
aggregate resource bounds and no reference verification inferred from text.

Limits remain 1,000,000 input bytes, 1,000 records and 100 references per record.
Collections apply byte/record limits to their aggregate. No database changes,
uploads, protected-source writes, network resolution or persisted drafts.
Readiness remains receipt eligibility; reference verification is reported
separately for compatibility with the existing workbench.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED. Only synthetic caller-supplied data is permitted.

## Progress

Baseline: pipeline 41/41 and content intake 30/30 passed on Python 3.13.15.
Existing isolated worktree/branch verified; no workspace creation needed.

Completed verification: pipeline 65/65, content intake 40/40, intake workflow
pure check 8/8, affected Django editorial consumer modules 45/45. Scoped Ruff
lint/format and `git diff --check` passed. No database suite or original source
acceptance was claimed; this change has no database adapter or migration.

One independent final reviewer found a shifted reference position after skipped
invalid pointers. Fixed with a regression observed RED then GREEN; pointer positions
now remain original in machine summaries and Arabic previews. Final pipeline/intake
and affected Django consumer suites passed after the fix. No deferred findings.
Existing compatibility contracts for blocked-row reference handling, separate
receipt readiness and reference verification, and trusted optional source pins
remain in force.

Synthetic acceptance identity: `apps.prepared_pipeline` inline fixture, raw input
SHA-256 `ebc4c23a55927c4643d5445caaf80478a7e8a517ec5b05f726da76f7fe3ad82c`.
New behavioral cases are generated synthetic inputs in the three new test files.
Verified PR base: `codex/20261024-w3-b6-ci-repair`, remote SHA matching the starting
base above. The owner already requested isolated push and one draft PR.
