# FAST8 integration evidence

Development integration only. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED. U03/U10 OWNER_APPROVAL_PENDING.

## Composition

Base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134). Target: `codex/20261026-fast7-ci-integration-pc1`. Integration branch: `codex/20261026-fast8-integration-pc1`. Each published source is one commit directly above that base. All 157 source paths are disjoint; every cherry-picked Git blob matched its source. All 16 commits were applied once with `git cherry-pick -x`; original authors and trailers are retained. No claim is made that four unpublished original PC2 FAST7 lanes were included.

| Source PR | Original SHA | Integration cherry-pick |
| --- | --- | --- |
| [#135](https://github.com/sami77337/fatwa-platform/pull/135) | `ecfcbe60e7a090fb5f34be81a341f9c34913739d` | `597baa2a8408ea5ad8421dda434598a35d569dc7` |
| [#136](https://github.com/sami77337/fatwa-platform/pull/136) | `3bb6984f162dfe16cf3615f18967bc0c9d8015a3` | `40bfdba40ad7ae939fb9aceba2f8bf59c5927253` |
| [#137](https://github.com/sami77337/fatwa-platform/pull/137) | `187ce00e94ad08d953b477da2bcf2ec86ddd1c02` | `699d49bb531ded973a5ea657fa7e79df1a6a6fc7` |
| [#138](https://github.com/sami77337/fatwa-platform/pull/138) | `1eb8e73007ea256da4a750998ee7e975683c9778` | `c97e3fb5234dd4a122026d191bdd3395f1cc8cd6` |
| [#139](https://github.com/sami77337/fatwa-platform/pull/139) | `bd3f23d7b628f8814873c44cc6610a93782c467b` | `dc9cec49e4e3bb7de7c6f456851eca8670ead231` |
| [#140](https://github.com/sami77337/fatwa-platform/pull/140) | `cdb507a3f8e1bff07593f73e14502780e9b4f7e8` | `0dcff2bd6ee5ca7c43d43fd178457b31960a0f7e` |
| [#141](https://github.com/sami77337/fatwa-platform/pull/141) | `b7bce06574549a9092a407f621723c58d40e19f8` | `826f6d531062055a10e8f20158ef985acc6ecffa` |
| [#142](https://github.com/sami77337/fatwa-platform/pull/142) | `7d9ad83729b7e335a9bab2b790cf59eb3d475ca6` | `d00b9c3cc7fdd5a055e8856a5a3adc317c85a1e2` |
| [#143](https://github.com/sami77337/fatwa-platform/pull/143) | `4870d8fb4e4d70ceee4981aa5b1b7f36409ac744` | `0fd3f9d56273913d85184f7525e92e69796f7b7d` |
| [#144](https://github.com/sami77337/fatwa-platform/pull/144) | `6600e92f047b75631168b00e13c93c6fa9f0db3b` | `fdace12f0c31d860d36cf27e0692a2790890da58` |
| [#145](https://github.com/sami77337/fatwa-platform/pull/145) | `05d2f3ae6f8936d7c07b318b168f43f6dd7dfa67` | `74569f9b14caefe0d6bd66c2e0fc5610df52b396` |
| [#146](https://github.com/sami77337/fatwa-platform/pull/146) | `c021cff7875cdec039086ffbc94001a91ea36672` | `9949fb64ccc80e82aa9d2722b138b223dd9c6aa5` |
| [#147](https://github.com/sami77337/fatwa-platform/pull/147) | `0702a285d880a6dab27d76e59972bb7a14d7fded` | `3a140d487bc5de645a8bd9e916042372eafe16ac` |
| [#148](https://github.com/sami77337/fatwa-platform/pull/148) | `5dd6dfb4d4ea30cd6571db6a7278bb5aeaa91f72` | `5a83de4850a6ade50c410296aca6013074961d8b` |
| [#149](https://github.com/sami77337/fatwa-platform/pull/149) | `bb38c82a97d86762ff93efeda875af4452fdb8ef` | `2058e3888ddc010ffc1cbcf4c66de931d891c75e` |
| [#150](https://github.com/sami77337/fatwa-platform/pull/150) | `93b22deadf349bb6ee6ed757ba320038e4ba6f89` | `f26a1751324595dd49331025f40377037a665322` |

## Security correction

PR147 `tests.fast8_ingest_adversarial.test_cli_fail_closed.CommandBoundaryTests.test_legacy_duplicate_key_diagnostic_does_not_echo_submitted_key` failed before the fix: the synthetic canary appeared in the duplicate-key diagnostic. It passed afterward, unchanged. The CLI still exits 1 with status INVALID. Duplicate-key errors no longer contain the submitted key; the outer boundary emits only fixed allowlisted contract messages, generic file/Unicode/CSV errors or JSON line/column numbers. Unknown ValueError text is not emitted. Rejection behavior and canonical source/output bytes remain intact. The directly affected stale-bundle diagnostic remains exact.

Additional diagnostic tests inject untrusted exception messages and filesystem paths for ValueError, OSError, UnicodeError, csv.Error and JSONDecodeError. This is not a blanket claim about every CLI in the repository.

## Functional connections and limits

`tests.integration.test_fast8` executes these real service compositions:

- All 20 stock queue cases bind dossier identity and original packet SHA to the packet verifier and export manifest. Eight cases have verified context receipts with DENY; twelve intentionally reject duplicate IDs, missing IDs or blocked rows. No grant follows a verified context. All eleven prepared rows retain their own payload/row identity and missing workflow joins.
- The transcript queue and segment timeline consume the same fabricated raw bytes, preserving input/source/prepared hashes, segment text, timestamps and canonical segment digests. Transcript rows remain ephemeral and separate from the stock queue; no answer, media or draft is created.
- The review export associates six rehearsal attempts only with exact case intake-7 and its original packet/source. Persisted review remains NOT_CONNECTED.
- Recovery retains the exact synthetic CSV row byte slice, ordinal, payload hash and duplicate finding; no resubmission or source mutation occurs.
- The reference dossier and fiqh navigation agree on edition 7001, source row and reference occurrence using an explicit synthetic in-memory catalog. A missing catalog remains NOT_CONNECTED. This is not PostgreSQL acceptance.
- Acceptance evidence preserves the exact FAST6 upstream report bytes and hash. Journey conformance executes a real case-DENY adapter probe on the prepared CSV row; this proves context identity only. Existing core permission authorization and persisted-review gaps remain NOT_CONNECTED. Source-preflight receipt verification does not assert supplied archives or owner acceptance.

`/dev/operator-navigation` is mounted through the existing local-only development guard. GET/HEAD require a loopback peer and localhost/loopback Host; production is denied. Malformed selectors and writes are rejected. The original lane test URLconf excludes the new project mount to avoid duplicate namespaces while retaining all original browser assertions. Browser conformance covers real local navigation at 320, 375 and 1280 pixels, with network/write guards unchanged.

## Executed local checks

Python 3.13.15, Django 5.2.18, Node 24.16.0, Windows Chrome. The initial composition SHA was `f26a1751324595dd49331025f40377037a665322`; integration fixes were uncommitted during these local runs. Final committed-SHA CI is recorded in the Draft PR, not inferred from this document.

| Collection | Observed result |
| --- | --- |
| 33 explicit FAST8 offline modules (listed in C6 workflow) | 347 collected: 346 PASS, one Windows symlink-permission skip |
| `tests.integration.test_fast8`, `test_fast8_mount`, `test_fast8_diagnostics` | 12 PASS |
| `tests.fast8_operator_nav.test_browser`, `tests.fast8_browser_conformance.test_conformance`, `tests.acceptance.fastbuild.test_browser` | 15 PASS, no skips |
| Nested FAST8 conformance Node/browser checks | 20 Node PASS; 17 actual Chrome PASS; cleanup PASS |
| Original FAST3/editorial browser checks | 17/17 PASS; prior packet-click timeout not reproduced locally |
| Directly affected legacy modules listed below | 148 PASS, no skips |
| `python -B -m tools.fast8_ingest_adversarial` | 21/21 PASS; no skip/xfail; exit 0 |
| Django system check, scoped Ruff check/format, git diff whitespace | PASS |

Commands use `python -B manage.py test <explicit module names> --settings=config.settings.test --noinput --verbosity=2`. All 33 offline module names are committed in `.github/workflows/c6-wave3.yml`; both new browser modules run explicitly in `.github/workflows/d6-wave4.yml` on Linux with required Chrome, exact collection count and unexpected-skip rejection. Existing jobs and gates remain enabled; no new matrix was added. Windows browser execution was local. The Windows symlink test is expected to execute on Linux CI; a Windows permission skip is not a symlink PASS.

Directly affected modules:

- `tests.content_intake.test_diagnostic_cli`
- `tests.content_intake.test_exact_prepared`
- `tests.content_intake.test_intake`
- `tests.content_intake.test_provenance`
- `tests.content_intake.test_validation_regressions`
- `tests.prepared_pipeline.test_batches`
- `tests.transcript_pipeline.test_pipeline`
- `tests.transcript_pipeline.test_cli`
- `tests.editorial_queue.test_services`
- `tests.editorial_queue.test_views`
- `tests.editorial_workbench.test_packets`
- `tests.editorial_export.test_services`
- `tests.integration.test_fast7bc`
- `tests.workflow_invariants.test_engine`

## Fixture identities

- `tests/fast8_transcript_queue/fixtures/fabricated_spans.json`: local raw SHA256 `01435680b826aa5b76d5ec77255ac266edf69bc487d16a659e0f9cb4ac3b2e5d`, 598 bytes (checkout line endings matter).
- `tools/fast8_permission_probes/scenarios.json`: local raw SHA256 `869a85ad96ff2cfd1ffa34c6848af10d1c1a9b327994d9bb305e256f55adf99f`, 28064 bytes (checkout line endings matter).
- `apps/fast8_journey_conformance/scenarios.json`: local raw SHA256 `1436ae475a29097914edb2259065523b8ffeff31390174c2eb19cf3a004c7eb5`, 17161 bytes (checkout line endings matter).
- Existing stock workbench: history + intake-1 through intake-8 + eleven prepared CSV/JSON/JSONL rows; all deliberately fabricated. Permission inventory pin: `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4`.
- Browser fixture contract SHA256: `17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9` in the observed local run.
- No owner ZIPs/private evidence were opened or committed. Source-owner acceptance: NOT_SUPPLIED / NOT_RUN.

## Remaining acceptance boundaries

Local Docker Linux engine was unavailable (named pipe missing). Optional `tests.fast8_fiqh_navigation.postgresql` and the browser harness existing-owned-PG catalog path remain NOT_RUN. Existing B6 PG17/18 uses disposable synthetic CI databases and is distinct from owner-source and optional FAST8 adapter acceptance. The FAST8 browser-only report intentionally has browser PASS but overall NOT_RUN when catalog prerequisites are absent.

ONE independent final review was completed. Its sole actionable finding was a corrupted UTF-8 BOM in the D6 workflow name key; it was corrected and the reviewer confirmed no remaining actionable findings. Initial integration-test authoring exposed mistaken assumptions about duplicate-ID eligibility, PreparedCase field names and adapter return shapes; tests were corrected to assert actual fail-closed contracts without changing source adapters. No original adversarial test was weakened.

No migrations, production writes, role grants, scholarly approval, publishing, external content services, main merge or deployment. Rollback is removal/revert of the isolated integration branch changes; no database rollback is required. Engineering progress is approximately 75?80% (about 78%), based on source-bound offline compositions, executable local navigation and explicit regression coverage. This is an estimate relative to the prior 70?75% planning baseline, not production readiness: owner sources, policy acceptance and persisted end-to-end connections remain outstanding.
