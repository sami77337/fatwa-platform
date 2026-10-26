# FAST7B offline comparison evidence — 2026-10-26

- Base: FAST6 PR #121, `667fd70217d794169c23569ce2df0396dcd27f7c`.
- Branch: `codex/20261026-fast7b-export-pc1`.
- Target: `codex/20261025-fast6-integration-pc2`; draft only.
- Changed areas: `apps/editorial_export/`, `tests/editorial_export/` only.
- Runtime: Python 3.13.15, Django 5.2.18, Ruff 0.17.0.

The existing CLI had export and exact replay verification, but no comparison
command. The new command verifies both bundles through that unchanged contract,
then records deterministic comparisons and full file inventories. The contract
accepts only this checkout's fixed snapshot: actual accepted pairs are identical.
Historical/different snapshots still fail verification. No trust bypass or new
data ingestion has been added to manufacture nonempty comparisons.

## Focused results

```powershell
python manage.py test tests.editorial_export.test_comparison tests.editorial_export.test_comparison_cli tests.editorial_export.test_services tests.editorial_export.test_cli tests.editorial_export.test_views --settings=config.settings.test --noinput
python -m ruff check apps/editorial_export tests/editorial_export
python -m ruff format --check apps/editorial_export tests/editorial_export
git diff --check
```

**35 tests passed**, no skips: 18 new comparison tests and 17 directly affected
export tests. Django system checks passed as part of the focused run. Ruff check,
format, and diff whitespace checks passed. After the shared CLI failure message
was updated to cover comparison output, its 12 directly affected CLI tests passed
again. No broad historical test suite was rerun. No failing test command occurred
during this implementation.

Public-path tests use the real authoritative replay, including both input orders
for tampering, updated manifest hashes, incompatible schemas, duplicate identities,
invalid file types/sizes, total byte bounds and explicit development opt-in.
CLI tests verify exclusive new output, input preservation, failure without output,
output-directory exclusion, bounded reads and pure subprocess operation without
Django setup. Nonregular-file rejection was simulated; no claim of a real Windows
symlink/junction race test is made.

Nonempty differences are tested only on private in-memory synthetic reports:
added/removed exact case keys despite duplicate external IDs, composed/decomposed
Unicode keys, packet digests, preparation/reference statuses, source/provenance,
batch membership and zero-row errors, null versus absence, typed values, array
order, and reverse direction. These altered reports are not accepted input bundles.
The full comparison output retains the existing JSON bounds and rejects overflow.

## Actual fixed-fixture replay

Inputs: the existing code-selected `intake_workflow.fixtures.synthetic_payload`,
`editorial_demo.revision_fixtures.REVISION_HISTORY_RECORD`, and preparation
`synthetic-csv`, `synthetic-json`, `synthetic-jsonl`, `synthetic-malformed` batches.
They contain 20 invented cases / 4 batches. Their exact input identities and hashes
remain listed in [VALIDATION.md](VALIDATION.md); no source fixtures were modified.

| Input file, identical on both sides | Bytes | SHA-256 |
| --- | ---: | --- |
| report.json | 142132 | `17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9` |
| cases.csv | 147942 | `8845e329911d59a7ab7a3a183732c5cfd3d53645177ebf7cb636933a597cf20a` |
| batches.csv | 3375 | `a0a1e58dd4451b34d047559b51fb17671431ecdf438ec2b081d79910d4ba2cd3` |
| manifest.json | 10041 | `44f4d707fba4eb1e07545cfb640188fe76d55de848924b12773214332b1453d2` |

Actual comparison: **1,414 bytes**, SHA-256
`2e5a5ceb74d0d8187e0c1ad26ea1bec48e8f936941edeefcf84127cd25d5938c`.
`identical: true`; all change lists empty; both complete file inventories recorded.

One independent final review found no blocking issues after inspecting the owned
implementation, tests, documentation and authoritative dependencies. Its separate
smoke check reproduced the exact comparison size/hash and rejected tampering of
the second input. It confirmed the documented fixed-snapshot limitation and made
no code edits or broad historical test reruns.

No database access or migration is needed. No PostgreSQL, private-record,
owner-archive or deployment acceptance is claimed. No shared settings, protected
source, permission grants, approvals, publication, PC2 FAST7 work or gates changed.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD.**
