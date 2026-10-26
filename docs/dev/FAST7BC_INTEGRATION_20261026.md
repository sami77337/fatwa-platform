# FAST7B+C integration — synthetic development only

Base: FAST6 Draft PR #121 at `667fd70217d794169c23569ce2df0396dcd27f7c`.
Branch: `codex/20261026-fast7bc-integration-pc1`.
Draft PR target: `codex/20261025-fast6-integration-pc2`, never main.
The four original FAST7 PC2 lanes are **NOT INCLUDED**. No other worktree,
computer, source branch, protected configuration or owner evidence was modified.

## Source identity

The isolated linked worktree was clean at the exact requested base. After fetch,
the remote target and PR #121 head matched that base. All eight source commits
are direct single-parent children of the base. Applied in this order with `-x`,
without conflicts:

| Lane | Original SHA | Applied SHA |
| --- | --- | --- |
| Queue | `3672b93a9a535308c8e56fc9057bcb3e83c1b103` | `10dcb6194f5df7b4f163da7803b4d02f3c72bcae` |
| Search | `88f3d4c5e9ba2e421c9f5902134bcf2d73f72268` | `6c26d2cad8441bd1cbf6602e5e1beb48da8157c4` |
| Export | `00abd5971039f83bc774a64f01f2cfd9047d4e64` | `57672c0c90ccedc401e13e5b943be8aa023bd778` |
| Browser | `ffadb976e65ff6060a1a675c20f2d337f72ed495` | `3c95d58c700b2fbe7b9ae5f603bafb308f20a9a6` |
| Fiqh reading | `7aebe39c5a659fe27e0dbd4d66e7d2d06776fc18` | `2965b5d47512d10cc1e80b4fb580701e5c1844ca` |
| Revision lineage | `95540319223a4ef31fa812a1870b709f95545e99` | `9f5f7f9d591455c82b11e23b6c28b85587375c8b` |
| Arabic quality | `af18db2b3c7b29056bff7e5d1e59337d6f8c9b55` | `7edc4b490b96fa65666cde523b26ffae14a10889` |
| Duplicate detection | `be257803bf3d1cdb20998f03ad76af561710b7cc` | `c08b59699112709f323c32c24446fef5a6300d91` |

All eight stable patch IDs, author names/emails/dates and `-x` trailers were
checked. All 70 imported file blobs match their respective original commits.
The only integration additions are this evidence, three cross-lane tests and
explicit C6/D6 coverage. No application code, source fixture, schema, settings,
dependency or migration was changed after cherry-picking.

## Verified behavior and limits

- Queue: review subsets with/without drafts retain exact case keys, source
  identities, stable neighbors and filtered return links.
- Search: exact normalized Arabic field matches rank ahead of partial matches,
  while returned text and revision/source identity stay original.
- Export: deterministic comparisons first verify both bundles against the
  checkout's fixed synthetic services. Different arbitrary snapshots are not
  accepted by that existing verifier; private differ tests are not evidence of
  public acceptance of modified bundles.
- Browser: one bounded startup budget and owned process-tree cleanup preserve
  sandbox, CSP, network allowlist, read-only requests and failure distinctions.
- Reading trail: source-pinned ancestor/neighbor navigation and research return
  identity, using the supplied synthetic catalog. Service/CLI only; no new page
  or accepted global fatwa taxonomy is claimed.
- Lineage: read-only consistency findings retain UNAVAILABLE evidence, including
  absent snapshot/event and draft/workflow bindings. No approval is inferred.
- Arabic quality: original text, offsets, Unicode and hashes remain intact.
- Duplicates: exact/normalized text candidates retain each source identity;
  candidate similarity never merges records or grants identity/approval.

The three integration tests exercise real services together: queue/search/
duplicates/quality/export identities, quality with lineage and missing evidence,
and reading trails with quality inspection and exact research returns. They
check immutable inputs and do not supply permissive verification mocks.

## Measured local evidence

Python 3.13.15, Django 5.2.18, Node 24.16.0, sandboxed Chrome 155.0.8059.85.
Source-suite/browser evidence was collected on clean `c08b596`; combined tests
also include the additive integration working changes. Final SHA CI results and
any final clean-head verification are recorded in the Draft PR.

| Check | Actual result |
| --- | --- |
| Eight lane Python suites | 248 collected: 247 PASS, 1 Windows skip of POSIX process-group ownership; 12.209s |
| Same suites plus cross-lane integration | 251 collected: 250 PASS, same 1 skip; 12.014s |
| Directly affected existing suites | 387 PASS; 17.555s |
| Node startup, policy, CDP and keyboard | 27 collected: 26 PASS, 1 Linux-only skip; 8.083s |
| CI Node dispatcher on startup/policy | Exit 0, 18 registered tests; OS-specific skip remains a skip |
| Guarded real Chrome | 3 Django tests PASS; 12.206s; editorial 17/17 cases, FAST5 navigation, FAST6 research journey |
| Local PostgreSQL catalog browser | NOT_RUN: five cases, E6 ownership/opt-in preflight not supplied |
| Django check, scoped Ruff lint/format, diff whitespace | PASS |

The FAST6 integrated CLI also returned exit 0 and its unchanged 282,974-byte
report hash `1f398dc8820159559f5afafee3054d592e2e5ac02992e7e9461c82ae582a97e5`.
Reading-trail, lineage and duplicate CLI smoke runs returned exit 0.

Affected modules: editorial_workbench, editorial_followup, editorial_dashboard,
reference_triage, research_bridge, workflow_rehearsal, revision_core,
fatwa_drafts, reference_links, fast6_journey, FAST4/FAST5 integration and editorial
audit provenance/export/adversarial tests. Database access is forbidden by these
SimpleTestCase suites; this is not local PostgreSQL acceptance.

The Chrome run exercised RTL and keyboard navigation at 1280/375/320px,
source-bound records, malformed input recovery, exact Arabic/CRLF, reference
links and GET/HEAD loopback policy. FAST5 recorded 159 requests and zero runtime,
network, HTTP or policy errors. No Chrome/DevTools failure reproduced locally;
the historical interaction flake is not declared fixed. Deterministic negative
startup and cleanup tests ran without relaxing guards or retrying scenarios.

One attempted package-label invocation failed collection because the top-level
`tests` is a namespace package (`module.__file__` is None). Explicit test module
labels resolved collection; all 251 tests were then executed. Initial format
check found two long assertions in the new test; Ruff formatted them and the
51-file scoped format check passed. Neither failure is omitted from evidence.

Reproduce the full new-feature invocation from the explicit FAST7B+C C6 step.
For affected suites, PowerShell:

```powershell
$dirs = 'editorial_workbench','editorial_followup','editorial_dashboard','reference_triage','research_bridge','workflow_rehearsal','revision_core','fatwa_drafts','reference_links','fast6_journey'
$labels = $dirs | ForEach-Object { Get-ChildItem "tests/$_" -Filter test_*.py -File } | Where-Object Name -ne 'test_browser.py' | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\','.').Replace('.py','') }
python -B manage.py test @labels tests.integration.test_fast4 tests.integration.test_fast5 tests.editorial_demo.test_audit_provenance_projection tests.editorial_demo.test_audit_export_contract tests.editorial_demo.test_audit_adversarial --settings=config.settings.test --noinput --verbosity=2
python -B manage.py test tests.acceptance.fastbuild.test_browser tests.acceptance.fast5.test_browser tests.fast6_journey.test_browser --settings=config.settings.test --noinput --verbosity=2
node --test tests/acceptance/fastbuild/startup.test.mjs tests/acceptance/fastbuild/policy.test.mjs tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
```

## Fixture identity

These are generated **synthetic** fixture/report hashes, not owner ZIP evidence.

| Input/report | SHA256 |
| --- | --- |
| Original intake synthetic payload | `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb` |
| Serialized immutable history intake | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` |
| Fiqh reading fixture | `b1abc9c56a6173f8c7c2f573af746aaee6140aaea58df26b6ffebd7803e12d98` |
| Lineage source payload | `b1b847aed7e44a5fb494cf2ce8cdcdb3828e8b4cbd46b025c3474773dfa2766c` |
| Arabic quality question.txt | `c404e1516245241183bed451b59dc5b813c6ed56f53b9b0acd3254c18683e206` |
| Arabic quality revision.txt | `4bdeae2ff8fff21127bf3452afdc9f5a6e4f3824e6bc85fec651b1a395f3f54c` |
| Duplicate report | `ebc0b8d85281e458dd32e938240b6b7c40598c79add6005c33d3f46966530382` |
| Export report.json | `17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9` |
| Export manifest.json | `44f4d707fba4eb1e07545cfb640188fe76d55de848924b12773214332b1453d2` |

Logs, label lists, browser reports and full identity measurements are in ignored
`.local/qa/fast7bc/`. C6 executes all eight lane suites and compatibility tests
on Windows/Linux plus Node lifecycle/policy tests. D6 adds guarded editorial
Chrome on its existing Linux job and uploads its reports. B6 is unchanged.
No checks, security guards, timeouts or platform matrices were removed/weakened.

## Execution ledger and delivery

1. Base/status/ancestry inspection: complete.
2. Eight exact `-x` cherry-picks and identity verification: complete.
3. Feature, affected, Node and guarded browser verification: complete as above.
4. Ruling: retain separate service/CLI boundaries; integration tests connect only
   existing exact identities. No new product UI or invented joins are in scope.
5. Ruling: use explicit Python modules in C6 to avoid namespace collection
   failure, matching the existing FAST6 step; no test is dropped.
6. Exactly one independent final read-only review completed on `c08b596` plus
   the four integration additions. No Critical, Important or Minor defect was
   confirmed. The reviewer independently checked eight patch/author/trailer
   identities and all 70 blobs, then ran the exact C6 selection: 251 tests,
   250 PASS/1 POSIX skip (11.927s), and Node: 26 PASS/1 Linux skip (7.917s).
   No second review or unverified fix was made.
7. Final commit/push, one Draft PR and exact-head B6/C6/D6 checks are recorded
   in the PR after this evidence commit, so its own SHA need not be self-referential.

Review rulings: Linux and final-head CI remain pending until those jobs actually
run; reviewed local affected/browser evidence is separate from independently
rerun tests. PostgreSQL/owner source acceptance and private or privileged product
operations remain outside this local synthetic scope. Distinct historical export
snapshots remain unsupported by the unchanged verifier. The four PC2 lanes remain
excluded. These boundaries prevent unsupported acceptance claims; they do not
turn missing functionality/evidence into PASS. No deferred minor findings.

No migration or data conversion; rollback is code-only. Owner source acceptance,
real private cases, scholarly approvals, publication and permission grants remain
outside this synthetic validation. No changes to YOLO, config.toml, sandbox,
approval settings, MCP or billing. No deployment or main merge.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED / GATES_HOLD.**
