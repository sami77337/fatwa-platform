# Feature registry checks

Read-only documentation checks for S6 issue #7. Requires Node.js 22 or newer and uses only the Node standard library. Node is a standalone documentation-tool dependency; it adds no frontend or product runtime dependency and changes no shared install files.

From the repository root:

```powershell
node --test --test-reporter=spec tools/feature_registry/tests/registry.test.mjs
node tools/feature_registry/validate.mjs
node tools/feature_registry/validate.mjs --source-dir _codex_input
```

The default command checks the schema, complete clause coverage, references, dependencies and fail-closed product gates. It verifies the repository source pins but reports ignored original exports as NOT_RUN when no source directory is provided. The explicit local-source mode verifies both supplied original files, all 479 IDs, exact line ranges/text hashes and approval anchors. Missing requested files fail with exit 1. Invalid CLI arguments exit 2; success exits 0. Output contains metadata only.

The validator implements only the JSON Schema keywords used by the checked-in schema, rejects unsupported keywords, and adds current-revision domain rules. It is not a general JSON Schema library. Pinned source hashes, exact unit approval anchors, U03/U10 pending state, disabled activation, held gates, D-067–D-070 distinctions, and absent product/removal/supersession evidence are checked independently of schema shape.

Tests use synthetic non-sensitive source text in memory, plus the committed derived metadata. They require no confidential export, network, database, Python or Django. Source verification uses the explicit local files only and prints no contents. All operations are read-only; no generated raw copies, external calls, database changes, grants or Git writes. File reads reject paths outside the declared root, including resolved symlink escapes, and reject inputs larger than 4 MiB.

Keep `_codex_input` ignored. Provide confidential exports locally to an authorized reviewer; do not upload them as public CI artifacts. Source-byte changes, including whole-file newline changes, require a reviewed revision rather than silently accepting a different pin. Current pins are defined in `SOURCE_PINS`, the registry manifest and the source report.

The 93 feature acceptance criteria are planned checks, not product test results. 479 traced clauses means source coverage, not 479 owner-accepted or implemented features. See [product scope](../../docs/product/README.md), [slices](../../docs/release-plan/SLICES.md), and [actual test evidence](../../docs/product/S6_RESULT.md).
