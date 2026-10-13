# S6 literal test evidence — 2026-10-13

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
