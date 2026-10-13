# S6 result — queued issue #10

**COMPLETED_LOCALLY — NON_PRODUCTION_DRAFT — NOT_DEPLOYED / GATES_HOLD.** Branch `codex/s6-scope-product-20261013`, unchanged checked-out SHA `e07851b3abf9a1d197088f037813f7b67d5cdfd8`. Registry revision **S6-20261013-R2**. No staging, commit, push, PR creation/update, merge, deployment, secrets or external sends.

D-072 now excludes the specialized Hadith Library from the first release: all 28 U10 clauses, including narrations, isnads, narrator knowledge/criticism, hadith rulings, comparisons, advanced specialist search and associated UI. FR-U10 uses `HADITH_LIBRARY_POST_FIRST_RELEASE`, classification/development scope `DEFERRED` and a separately dated `release_timing` record. Its precise `owner_approval` remains `OWNER_APPROVAL_PENDING`, removal remains `NOT_DECIDED` and activation remains `DISABLED`. No later release number/date is selected.

The owner-decision document records dated provenance from the supplied owner-authored queued issue #10 and distinguishes that evidence from an independently verified live Decision Log. The broader D-069 science-source slice is separate. Both D-068 feature records and their V1/V2 slices remain unchanged: human-reviewed inline citation assistance is planned V1 independently of U10, external ChatGPT is V2, and no AI is activated.

## Changed files — S6 ownership only

- [feature_registry.json](feature_registry.json): U10 timing, D-072 source anchors and specialist slice/source identity; separate broader science dependency.
- [feature_registry.schema.json](feature_registry.schema.json): R2, source-record metadata and explicit release-timing structure.
- [D072_RELEASE_DEFERRAL.md](D072_RELEASE_DEFERRAL.md): new non-sensitive task-derived decision record with date, exact scope, provenance and hash identity.
- [OWNER_DECISIONS_NEEDED.md](OWNER_DECISIONS_NEEDED.md): timing resolved; later exact clauses/source/rights policies remain pending.
- [SOURCES.md](SOURCES.md) and [README.md](README.md): updated evidence basis and classification counts.
- [SLICES.md](../release-plan/SLICES.md): specialist post-first-release scope, broader science distinction and preserved D-068 V1.
- [validate.mjs](../../tools/feature_registry/validate.mjs): exact provenance, release rollback negatives, source/rights blockers and independent citation scope.
- [registry.test.mjs](../../tools/feature_registry/tests/registry.test.mjs) and [tool README](../../tools/feature_registry/README.md): 25 added regressions and updated commands/evidence meanings.
- [TEST_LOG.md](TEST_LOG.md) and this result: true local outcomes, tested artifact hashes and limitations.

## Actual checks

| Command | Outcome |
|---|---|
| `node --test --test-reporter=spec tools/feature_registry/tests/registry.test.mjs` | Exit 0; 68 passed, 0 failed, 0 skipped |
| `node tools/feature_registry/validate.mjs` | Exit 0; registry/repository/tracked D-072 evidence PASS; ignored task copies and originals NOT_RUN |
| `node tools/feature_registry/validate.mjs --source-dir _codex_input` | Exit 0; task-copy hashes/anchors and both original source pins, all 479 identities/ranges/text hashes and approval anchors PASS |
| `node --check tools/feature_registry/validate.mjs` | Exit 0; empty stdout/stderr |
| `node --check tools/feature_registry/tests/registry.test.mjs` | Exit 0; empty stdout/stderr |
| `git --no-optional-locks diff --check` | Exit 0; no whitespace errors; informational core.autocrlf line-ending warnings |

Node v24.16.0. [TEST_LOG.md](TEST_LOG.md) stores literal output and the SHA256 of the tested registry/schema/code/decision record. The 479 clause anchors, all prior evidence and source pins, both D-068 records/slices, gates/deny defaults and unrelated feature groups were compared against the clean starting registry and remain unchanged. Negative tests reject returning U10 to V1, false detailed approval/removal, partial deferral, missing provenance/source/rights blockers and dependent or post-V1 D-068 citations.

## Remaining limitations and handoff

No blocker remains for this local correction. Live Decision Log revisions and original owner messages are not independently verified; the supplied queued issue is the explicit evidence basis. U03's 48 and U10's 28 exact clauses remain pending. A lawful specialist Hadith corpus, source rights/policies and integrated product acceptance are still absent. Django/PostgreSQL, TOC import, UI/accessibility, security/performance and provider tests are NOT_RUN; this change does not claim any product implementation.

PR #9 was not updated: the current user instruction overrides the queued issue's PR handoff request. Review the local owned-path diff and [test evidence](TEST_LOG.md). No commit, push, PR action, merge or deployment was performed. Registry documentation must never drive runtime grants or publication. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED. Final Figma remains deferred under D-070.
