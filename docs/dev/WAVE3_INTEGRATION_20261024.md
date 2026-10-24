# Wave 3 integrated development candidate - 2026-10-24

Development only: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED. No scholarly approval, publication,
private records, production writes, or privileged grants.

## Scope and provenance

Verified remote base: `codex/20261024-w3-b6-ci-repair` at
`293cfebccb18e0231926dedfb920f8163d9ab624`.
Integration branch: `codex/20261024-fastbuild-integration`.
Tested/reviewed product SHA: `e9127fee23ce618c166de15b55b254ff08cca777`.
The following documentation-only commit does not change that product tree.

Fetched all 16 actual PR heads and verified their advertised SHAs and ranges.
Applied all 20 commits with `git cherry-pick -x`, retaining author metadata,
ordering and the four review fixes. No conflicts or integration code edits.
All 20 binary Git diffs match their original diffs byte-for-byte; all 33
changed product/test paths equal the union of the original patches.

| PR | Original commit | Integrated commit |
|---|---|---|
| #76 | `d6c049856c15e6d6b5d4052b6d39ff3fd5596fbf` | `0fa0b59a9f150fd1945ccb9451db7d7a9d9b1ed4` |
| #77 | `99550404e9ea007132c948053342cbbadf2a5fc0` | `8389c5f0d462639d4eaf7d801b60d0fb87e90550` |
| #80 | `aa841dd90c8be481f0a241638be4a6230996cfb8` | `48cbedc63f640bbd59d8513d83146ea0dfe56ae5` |
| #80 | `ed40e4c99cb0df820d880657870b530a9b95ffd4` | `0f80033591a12a0cce84ee9a9fb222567093bba6` |
| #83 | `5bf525a8f9445e01d18ff0abf0f33e076748c321` | `2ded61a7c69276c89d8fe7e6b84d1ab4f9be5d41` |
| #79 | `e49982e2bc5e7231328004acd09956f8c4bd2331` | `d20a863a54c89c2cbb4196c381ca865baa253118` |
| #78 | `99e1fd36cb2263ca6720f7e213c92921cdb459de` | `5843b451477d76418862e74a4fd12307776c5048` |
| #85 | `b92b79cad0163877d65d6bee8e9d04e16d2ee45b` | `db4b6429f3294420a8116575cb7de5e9b482c8c8` |
| #85 | `130d7435e860aee912f84610b5f286c0812c9452` | `5c6e3b9a4fcec2cf9d85a75489c5096656220eff` |
| #88 | `c9c4dad40fd4ad843e2a9a05d2b2de9877340bda` | `21ee6957d411cd94e17982ab17cbaf66f964383f` |
| #82 | `3dae5511a8cbb0027b3fee7a66bf2b5d36543737` | `2c4d3138aff0951942a990e36c9ee56fcd622e5f` |
| #82 | `a7c9d464c10750a3abfed69a78af35c204e629db` | `78a73d2e81d0de6b9ac8ff78bad6c49fd56364b2` |
| #84 | `c296e1f5d48ee1761dc113c9a66a08742cfa5cc8` | `805bc2bad83cbfff26dd92f6984272996374f6e9` |
| #89 | `4c97dee5b02c4515b8a86596bc4035795a6f7ecb` | `2b5047642c5f727addf4a3bf7f770c0988d6f0d0` |
| #87 | `9fdb814e691079900c0f7cde7f0a469f10efe509` | `a375a9d8564035385b2028d57fa86915cde7330f` |
| #87 | `c160483fad5ecb992b255c12c916889be4fb3725` | `400dfc68bce96198d83ebe12a9608c9a18c41ab7` |
| #81 | `83e8ec7271885a3d171c96e8155d99adb1852abe` | `7eb9f31928c343002e793488ce99878a0162059b` |
| #86 | `b0b79ab9cd13f4f0667403f6a2664df81fb1cc29` | `0821eb5a3160632d5e834e17a7d1d347f5a3527e` |
| #90 | `bf4e27a82b06b158001ad8eea2fea7653910c48e` | `8798dc38d1ba7d19123663e83b2da500e902dc95` |
| #91 | `74b2e0b7e547f5d12c69aec65650a2c8c719d4d4` | `e9127fee23ce618c166de15b55b254ff08cca777` |

## Working functionality

- Audit: strict bounded JSON DTO validation, deterministic query/pagination
  helpers used by the existing guarded view, and immutable provenance/chronology
  projection. The projection is a pure library API, not a new public route.
- Revision UI: existing synthetic comparison page has previous/next difference
  links; history and comparison forms expose Arabic selection context, keyboard
  targets and accessible region labels without changing source text.
- Reference diagnostics: strict serialization, deterministic grouping, escaped
  Arabic HTML/text rendering and explicit evidence limitations. These remain
  pure APIs; no new public diagnostic endpoint is claimed.
- Revision core: exact-identity previous/next history navigation, immutable
  provenance aggregates, and serialization/Unicode/bounds regression coverage.

## Verification

Python 3.13.15, Django 5.2.18, Windows. `config.settings.test`, loopback PostgreSQL
port 1, empty password/service, synthetic inputs only; no database setup.

- All 16 new test modules in one Django invocation: **143 passed**.
- Selected directly affected audit JSON/query/guard, revision HTML/XSS/selection,
  diagnostic serialization and core compatibility checks: **26 passed**.
- Shared comparison previous/next parity across all 36 revision pairs: **1 passed**.
- Total **170 tests passed**; each invocation exited 0 and Django system checks
  reported no issues. No accepted historical full suite or B6 rerun.
- `git diff --check 293cfeb HEAD`: passed.
- Changed-file `ruff check`: **not clean**, 10 I001 import-order findings.
  Four are inherited from the base (views.py twice, workflow_audit.py,
  diagnostics.py); six arrive unchanged in new audit/diagnostic test files.
  Original patches remain intact; no unrelated formatting rewrite.
- Independent read-only final review of the product SHA above: no Critical,
  Important or Minor findings; verified patch IDs and combined A/C contracts,
  UI navigation/escaping, source identities, and unchanged gate settings.

Reproduce the new-test invocation in PowerShell from this branch:

```powershell
$env:PYTHONUTF8='1'
$env:DJANGO_SETTINGS_MODULE='config.settings.test'
$env:PGHOST='127.0.0.1'
$env:PGPORT='1'
$env:PGPASSWORD=''
$env:PGSERVICE=''
$env:FATWA_PRODUCTION='0'
$new = git diff --name-only --diff-filter=A 293cfeb HEAD -- tests |
  Where-Object { $_ -match '/test_[^/]+\.py$' } |
  ForEach-Object { ($_ -replace '/', '.') -replace '\.py$', '' }
python manage.py test @new --noinput --verbosity 1
```

Source integrity: 27 protected Git blobs unchanged (fixtures, migrations,
coordination/reference assets and guard metadata). Eight pinned worktree files
match base Git bytes exactly; six synthetic fixture inputs also match the base
checkout under the existing Git attributes. No line-ending settings changed.
Exact synthetic revision fixture identity:
`apps/editorial_demo/revision_fixtures.py`, SHA256
`2dded1030f319e039565192f24a3b170b170113ff8e9a1fe2e08cc587a82ea22`.
Synthetic five-level JSON checkout SHA256:
`fa37b33efc506f3deb9f8d2f32223ef8bce85c9748fb840061b359437b3c94d3`.
Original owner archives were not used or accepted in this integration.

## CI and limitations

- Accepted base [B6 run 40082108991](https://github.com/sami77337/fatwa-platform/actions/runs/40082108991)
  succeeded, including PostgreSQL 17/18. This remains base evidence only.
- Base [C6 run 40082108998](https://github.com/sami77337/fatwa-platform/actions/runs/40082108998)
  and [D6 run 40082108993](https://github.com/sami77337/fatwa-platform/actions/runs/40082108993)
  have four never-started jobs. Every annotation reports failed account payments
  or a spending-limit block; steps are empty and logs unavailable.
  **NOT_EXECUTED - billing/service block**, not a code-test failure.
- No C6/D6 retry: no evidence that the external block changed. Their broad local
  dispatchers repeat historical suites, so the relevant focused tests above were
  used instead. Current integrated-head C6/D6 and PostgreSQL are **NOT_RUN**.
- All existing workflows trigger on push/PR without selective dispatch.
  The documentation commit uses `[skip ci]` to honor the accepted-B6/no-retry
  constraint; no workflow, billing, credential or sandbox settings were changed.
  Skipped/pending checks are not passes. The PR remains Draft.
- Browser/screen-reader execution is NOT_RUN; accessibility evidence is SSR only.
  No production readiness or official gate advancement is claimed.
