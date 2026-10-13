# S6 literal test evidence — queued issue #10 — 2026-10-13

Current revision: **S6-20261013-R2**. Checked-out SHA: `e07851b3abf9a1d197088f037813f7b67d5cdfd8`. Branch: `codex/s6-scope-product-20261013`. Changes remain local, unstaged and uncommitted. Runtime: Node.js `v24.16.0` on Windows. Actual commands used Node child-process argument arrays because the unified shell failed before process launch with `helper_unknown_error: setup refresh had errors`. No network, external provider sends or Git mutations were performed.

## R2 tested artifact identities

| Tested working-tree artifact | SHA256 |
|---|---|
| docs/product/feature_registry.json | `c4e8f1cefd70061e3e34e8bed9d1eb2faef6d855407c0edc30e20aebe3c34a63` |
| docs/product/feature_registry.schema.json | `eeed17b23930872862e42bfb068464e36bd7ba095a1305ab5ba2b9d75b8d65f8` |
| tools/feature_registry/validate.mjs | `889fed84112e2463da98f1b653dec9e9e131df5681d6857ecb452876975c4a06` |
| tools/feature_registry/tests/registry.test.mjs | `40cf3c441fd32be522d1c5ffde7d424e9e08d4494953e2b9c7cd1d997b560038` |
| docs/product/D072_RELEASE_DEFERRAL.md | `2cc176f8d30e2468d6d9c13c14244e30dc54f9bbc0cd1e1c994345afbe97be76` |

Acceptance-input identity: the ignored `_codex_input/queued_issue_10.md` is 3,440 bytes with SHA256 `5c731493499ac0d3389d8dd480df6e0c5a9207d87d38d1f125be6cffdcbc56a2`; D-072 decision/scope evidence uses one-based inclusive lines 4–6. Both PINNED-20261010 original exports and the issue #7 copy were also actually present and verified in explicit-source mode; exact identities/hashes are in [SOURCES.md](SOURCES.md). Unit tests use synthetic original clause text in memory and the tracked non-sensitive decision summary. They do not establish product acceptance or independently verify the live Decision Log.

The baseline checks passed before editing: 43 tests, 0 failed; explicit-source validation exit 0. Final R2 checks below: **68 tests, 0 failed, 0 skipped**, all five Node commands exit 0. The 25 additional tests protect D-072 scope/provenance and D-068 independence. Registry inventory remains 24 groups, 479 unchanged clause anchors and 93 planned product criteria (all NOT_RUN). All five previous source pins, all previous evidence, both D-068 records/slices and the complete context gates/deny defaults were compared with the clean starting registry and found unchanged. Unrelated feature groups are unchanged; FR-D069-OTHER only loses the U10-specific approval dependency when separating the broader science-source slice.

## R2 literal command output

### node --test --test-reporter=spec tools/feature_registry/tests/registry.test.mjs

Exit code: 0.

```text
✔ derived registry has complete source coverage while all product checks remain NOT_RUN (12.5957ms)
✔ schema distinguishes all eight requested classifications without fabricating records (0.1307ms)
✔ D072 separates first-release deferral from exact U10 acceptance and D068 planned V1 (0.1401ms)
✔ D072 U10 cannot be assigned to V1_KNOWLEDGE (11.0364ms)
✔ D072 U10 cannot be assigned to AI_V1_LATER (9.1652ms)
✔ D072 U10 cannot be assigned to PUBLIC_CATALOG_DEV (8.8516ms)
✔ D072 U10 cannot be assigned to OTHER_SCIENCE_LATER (7.7073ms)
✔ D072 rejects the complete pre-decision U10 timing rollback (7.9454ms)
✔ D072 release timing cannot be silently omitted (7.6999ms)
✔ D072 deferral cannot approve exact U10 clause contents (8.2766ms)
✔ D072 is deferral rather than U10 removal (9.9815ms)
✔ D072 cannot exclude fewer than all 28 clauses (8.9314ms)
✔ D072 cannot undo first-release exclusion (8.5859ms)
✔ D072 requires its exact dated owner timing decision (8.3979ms)
✔ D072 evidence cannot be replaced by a clause-approval mandate (8.2293ms)
✔ D072 must remain linked to the U10 feature (7.8311ms)
✔ D072 task provenance cannot use an invented source locator (7.7293ms)
✔ D072 cannot lend release-timing authority to another unit (7.6255ms)
✔ D072 specialized Hadith source and rights blockers cannot be omitted (7.7059ms)
✔ D072 specialist slice keeps gates and detailed acceptance dependencies (7.9978ms)
✔ D072 specialist U10 deferral cannot govern broader science data (7.5126ms)
✔ D068 planned V1 citation assistance cannot move after the first release (7.5499ms)
✔ D068 citation assistance cannot depend on U10 approval or a specialist corpus (8.6519ms)
✔ D072 broader science feature does not inherit specialist U10 approval (8.1957ms)
✔ D068 planned V1 slice cannot acquire specialist U10 dependencies (7.4232ms)
✔ D072 tracked decision record verifies real bytes and rejects changed summary bytes (6.7525ms)
✔ default CLI verifies tracked D072 while accurately reporting ignored task sources NOT_RUN (51.3858ms)
✔ U03 cannot be approved through a narrower decision (8.1591ms)
✔ U10 cannot be approved through a narrower decision (7.855ms)
✔ generic encouragement cannot serve as an exact unit approval (7.4756ms)
✔ a new invented unit cannot acquire documentary approval (7.7983ms)
✔ product approval cannot imply implementation verification (7.3972ms)
✔ planned feature checks cannot claim PASS (7.319ms)
✔ S6 registry tests cannot become product-test evidence (7.6238ms)
✔ activation remains disabled (7.1272ms)
✔ gate B cannot be cleared (8.6302ms)
✔ C D E and Phase01 remain held (7.9298ms)
✔ historical permission rows confer no grants (7.3471ms)
✔ DOMAIN_TRANSACTION is no runnable principal (7.0421ms)
✔ book 622 is neither global taxonomy nor published fatwas (6.8022ms)
✔ AI remains disabled in current work (6.931ms)
✔ D068 external ChatGPT stays V2 (7.2886ms)
✔ D070 final design cannot enter current development (7.3649ms)
✔ sensitive workflows cannot join the read-only metadata slice (7.3504ms)
✔ missing clause coverage cannot retain a 479 claim (7.3404ms)
✔ missing unit group cannot retain a 479 claim (7.2904ms)
✔ duplicate IDs are rejected (7.6259ms)
✔ exact source pins cannot be silently replaced (7.6489ms)
✔ source revisions and trust categories cannot be silently replaced (7.4011ms)
✔ reversed line ranges are rejected (7.5401ms)
✔ a changed clause number is rejected (7.2462ms)
✔ dangling evidence and dependency refs are rejected (7.4911ms)
✔ catalog source blockers cannot be omitted (7.2797ms)
✔ criteria cannot borrow unrelated unit clauses (7.5057ms)
✔ owner feature removal is not chosen by this worker (7.2163ms)
✔ supersession requires an actual newer decision (7.3045ms)
✔ raw source payloads are not part of the derived registry (9.176ms)
✔ unknown classifications fail closed (9.9117ms)
✔ schema rejects malformed types and unsupported schema keywords (6.9585ms)
✔ synthetic originals verify normalized line anchors, IDs and text hashes (26.2561ms)
✔ changed original bytes fail their pin (3.0176ms)
✔ clause locator/hash mismatch fails independently of whole-file SHA (24.6498ms)
✔ false clause identity cannot pass through recomputed index SHA (25.3931ms)
✔ one supplied original cannot imply both were verified (2.0226ms)
✔ malformed JSONL returns a metadata-only error (23.3322ms)
✔ readContained rejects traversal beyond its explicit root (3.9519ms)
✔ CLI uses explicit local evidence mode and fails on missing originals (49.1294ms)
✔ CLI rejects unknown or incomplete arguments without reading arbitrary inputs (67.9563ms)
ℹ tests 68
ℹ suites 0
ℹ pass 68
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 783.4354
```

Stderr: empty.

### node tools/feature_registry/validate.mjs

Exit code: 0.

```text
REGISTRY PASS: 24 feature groups; 479 exact clause anchors; U03=48/U10=28 pending
REPOSITORY_EVIDENCE PASS: AGENTS and coordination SHA256/line anchors
D072_RECORD PASS: tracked task-derived summary SHA256/line anchors; U10 post-first-release; exact acceptance pending; D068 planned V1 unchanged
TASK_EVIDENCE NOT_RUN: ignored issue copies not read; live Decision Log NOT_VERIFIED
PINNED_ORIGINALS NOT_RUN: use --source-dir with the ignored local exports
PRODUCT_ACCEPTANCE NOT_RUN: 93 planned group criteria; no integrated product or TOC fixture tested
NOT_DEPLOYED / GATES_HOLD: B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; all product activation DISABLED
```

Stderr: empty.

### node tools/feature_registry/validate.mjs --source-dir _codex_input

Exit code: 0.

```text
REGISTRY PASS: 24 feature groups; 479 exact clause anchors; U03=48/U10=28 pending
REPOSITORY_EVIDENCE PASS: AGENTS and coordination SHA256/line anchors
D072_RECORD PASS: tracked task-derived summary SHA256/line anchors; U10 post-first-release; exact acceptance pending; D068 planned V1 unchanged
TASK_EVIDENCE PASS: issue 7 and queued issue 10 SHA256/line anchors; live Decision Log NOT_VERIFIED
PINNED_ORIGINALS PASS: both source SHA256 pins, 479 identities, line ranges, clause hashes and approval anchors
PRODUCT_ACCEPTANCE NOT_RUN: 93 planned group criteria; no integrated product or TOC fixture tested
NOT_DEPLOYED / GATES_HOLD: B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; all product activation DISABLED
```

Stderr: empty.

### node --check tools/feature_registry/validate.mjs

Exit code: 0.

```text
(stdout empty)
```

Stderr: empty.

### node --check tools/feature_registry/tests/registry.test.mjs

Exit code: 0.

```text
(stdout empty)
```

Stderr: empty.


### git --no-optional-locks diff --check

Exit code: 0. Stdout: empty. Stderr contains Git core.autocrlf informational line-ending warnings; no whitespace error was reported. Literal stderr:

```text
warning: in the working copy of 'docs/product/OWNER_DECISIONS_NEEDED.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/product/README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/product/S6_RESULT.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/product/SOURCES.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/product/TEST_LOG.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/product/feature_registry.json', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/product/feature_registry.schema.json', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/release-plan/SLICES.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tools/feature_registry/README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tools/feature_registry/tests/registry.test.mjs', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tools/feature_registry/validate.mjs', LF will be replaced by CRLF the next time Git touches it
```

The new untracked D-072 record was also checked directly for trailing whitespace and an ending newline. Git diff checks cover tracked modifications only.

Product acceptance, Django/PostgreSQL, TOC import, UI/accessibility, performance and provider integration tests are **NOT_RUN**. They are outside this corrective documentation scope and the integrated application/TOC fixtures are not present in this worktree. U03/U10 exact approval and U10 later source/rights policies remain pending. Gates stay B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED. PR #9 was not modified because the current user instruction prohibits PR actions.

## Historical R1 evidence from the previous issue #7 run

The following evidence predates issue #10 and is preserved as history; its 43-test count and artifact hashes do not describe R2.

Base SHA: `08f9e25e8ada9af56561d815f74b2c7ec9ba7ead`. Branch: `codex/s6-scope-product-20261013`. Changes are uncommitted by design; code/data identities below identify the tested working-tree files. Runtime: Node.js `v24.16.0` on Windows. Execution used Node child-process calls with argument arrays because the unified shell helper failed before process launch. No network or Git writes.

| Tested working-tree artifact | SHA256 |
|---|---|
| docs/product/feature_registry.json | `31b86dce50eea30154c20c37f20c8b782bad529319f5886bf6054012a11c21f9` |
| docs/product/feature_registry.schema.json | `003a7b916cc6755fb4d7e317a5650b066951d2edaaade863eb063edb1802bcf5` |
| tools/feature_registry/validate.mjs | `9981ed1c49d0402442db5c7847d72fc5562f7d7f295c113dcf5c30afc438f825` |
| tools/feature_registry/tests/registry.test.mjs | `5e92e8cf6496b4ace8706f406dd601113eae6716fea4ff13be39cadf21e95e1b` |

Original acceptance-input identities are the two ignored PINNED-20261010 exports in [SOURCES.md](SOURCES.md). Unit tests use synthetic source text only in memory and do not require those exports. Product acceptance, Django/PostgreSQL, TOC import, UI/accessibility, performance and external provider tests remain NOT_RUN.

## node --test --test-reporter=spec tools/feature_registry/tests/registry.test.mjs

Exit code: 0.

```text
✔ derived registry has complete source coverage while all product checks remain NOT_RUN (12.4168ms)
✔ schema distinguishes all eight requested classifications without fabricating records (0.1333ms)
✔ U03 cannot be approved through a narrower decision (11.2297ms)
✔ U10 cannot be approved through a narrower decision (9.6391ms)
✔ generic encouragement cannot serve as an exact unit approval (9.237ms)
✔ a new invented unit cannot acquire documentary approval (8.1587ms)
✔ product approval cannot imply implementation verification (7.925ms)
✔ planned feature checks cannot claim PASS (7.9828ms)
✔ S6 registry tests cannot become product-test evidence (7.9613ms)
✔ activation remains disabled (8.8818ms)
✔ gate B cannot be cleared (9.1579ms)
✔ C D E and Phase01 remain held (8.4764ms)
✔ historical permission rows confer no grants (7.9042ms)
✔ DOMAIN_TRANSACTION is no runnable principal (7.4333ms)
✔ book 622 is neither global taxonomy nor published fatwas (7.4133ms)
✔ AI remains disabled in current work (7.3208ms)
✔ D068 external ChatGPT stays V2 (7.8916ms)
✔ D070 final design cannot enter current development (7.9534ms)
✔ sensitive workflows cannot join the read-only metadata slice (8.1473ms)
✔ missing clause coverage cannot retain a 479 claim (7.753ms)
✔ missing unit group cannot retain a 479 claim (7.7566ms)
✔ duplicate IDs are rejected (8.2879ms)
✔ exact source pins cannot be silently replaced (9.3614ms)
✔ source revisions and trust categories cannot be silently replaced (7.7519ms)
✔ reversed line ranges are rejected (7.9632ms)
✔ a changed clause number is rejected (9.7266ms)
✔ dangling evidence and dependency refs are rejected (7.8531ms)
✔ catalog source blockers cannot be omitted (8.0949ms)
✔ criteria cannot borrow unrelated unit clauses (7.6773ms)
✔ owner feature removal is not chosen by this worker (8.2207ms)
✔ supersession requires an actual newer decision (7.6849ms)
✔ raw source payloads are not part of the derived registry (9.1272ms)
✔ unknown classifications fail closed (8.2378ms)
✔ schema rejects malformed types and unsupported schema keywords (6.7283ms)
✔ synthetic originals verify normalized line anchors, IDs and text hashes (25.7243ms)
✔ changed original bytes fail their pin (3.2962ms)
✔ clause locator/hash mismatch fails independently of whole-file SHA (24.4004ms)
✔ false clause identity cannot pass through recomputed index SHA (24.7855ms)
✔ one supplied original cannot imply both were verified (2.1338ms)
✔ malformed JSONL returns a metadata-only error (23.37ms)
✔ readContained rejects traversal beyond its explicit root (6.1371ms)
✔ CLI uses explicit local evidence mode and fails on missing originals (49.6715ms)
✔ CLI rejects unknown or incomplete arguments without reading arbitrary inputs (67.1226ms)
ℹ tests 43
ℹ suites 0
ℹ pass 43
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 563.4822
```

Stderr: empty.

## node tools/feature_registry/validate.mjs

Exit code: 0.

```text
REGISTRY PASS: 24 feature groups; 479 exact clause anchors; U03=48/U10=28 pending
REPOSITORY_EVIDENCE PASS: AGENTS and coordination SHA256/line anchors
PINNED_ORIGINALS NOT_RUN: use --source-dir with the ignored local exports
PRODUCT_ACCEPTANCE NOT_RUN: 93 planned group criteria; no integrated product or TOC fixture tested
NOT_DEPLOYED / GATES_HOLD: B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; all product activation DISABLED
```

Stderr: empty.

## node tools/feature_registry/validate.mjs --source-dir _codex_input

Exit code: 0.

```text
REGISTRY PASS: 24 feature groups; 479 exact clause anchors; U03=48/U10=28 pending
REPOSITORY_EVIDENCE PASS: AGENTS and coordination SHA256/line anchors
PINNED_ORIGINALS PASS: both source SHA256 pins, 479 identities, line ranges, clause hashes and approval anchors
PRODUCT_ACCEPTANCE NOT_RUN: 93 planned group criteria; no integrated product or TOC fixture tested
NOT_DEPLOYED / GATES_HOLD: B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; all product activation DISABLED
```

Stderr: empty.

## node --check tools/feature_registry/validate.mjs

Exit code: 0.

```text
(stdout empty)
```

Stderr: empty.

## node --check tools/feature_registry/tests/registry.test.mjs

Exit code: 0.

```text
(stdout empty)
```

Stderr: empty.

## Additional observations and corrected development failure

`git --no-optional-locks diff --check` returned exit 0 with empty stdout/stderr. This applies to tracked diffs; newly created owned files were inspected separately and not staged.

`python --version` could not start (spawn python ENOENT). `py --version` returned exit 1 with literal output:

```text
No installed Python found!
```

Python is not needed by the S6 Node checks. No Django/PostgreSQL command was run or reported passing. The base contains no manage.py, root dependencies, application or database fixture.

The first default and explicit-source validation attempts returned exit 1 because the initial ID pattern excluded underscores used in source/dependency identifiers. Literal stderr excerpt (the full output repeated the same format error):

```text
REGISTRY FAIL
$.sources[0].id: invalid format
$.sources[1].id: invalid format
$.sources[4].id: invalid format
```

The schema ID pattern was corrected to allow stable underscore identifiers. The final commands/results above were run after that correction and all final S6 checks passed. Earlier shell read attempts did not run: the unified execution helper returned `setup refresh had errors`. Filesystem and command access through the available Node tool succeeded within the same owned worktree.
