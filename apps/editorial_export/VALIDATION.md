# FAST4 export validation — 2026-10-25

Base: FAST3 PR #106, `a149b39bfd624e330762459a7c3e0b4febc7187b`.
Branch: `codex/20261025-fast4-export-pc2`. See the delivering commit for final SHA.

Python 3.13.17 using the existing external `fast3-venv`; pinned Django 5.2.18.
The focused command in [README.md](README.md#focused-verification) passed **82
tests**, including 17 new export tests and 65 directly used preparation/packet
tests, with no skips. Ruff check/format (10 owned Python files), Django system
check and `git diff --check` passed. No historical full suite or Actions job rerun.

The initial `manage.py test tests.editorial_export ...` package-discovery command
failed before test execution because top-level `tests` is a namespace package
(`module.__file__` is None). Explicit module names in the documented command
resolved this without modifying shared test infrastructure. Test-first runs also
observed missing service/CLI/route failures and the empty CSV header bound failure
before implementation/fix; these are not claimed as passing runs.

Pure Python 3.13 without Django: executable CLI export and verify both returned 0.
Four files total **303,490 bytes**. Repeat service builds and replay were identical;
tests reject coordinated file/manifest tampering, partial/extra/oversized outputs,
existing output directories, invalid Unicode, duplicate identities and production
guards. HTTP tests cover all 20 packet links and four attachment hashes. A separate
Chrome mobile check at viewport 390×844 found clientWidth=scrollWidth=375, 30 unique
IDs, and no horizontal overflow; only the existing local stylesheet was loaded.
The temporary loopback WSGI preview was stopped after inspection.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| report.json | 142132 | `17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9` |
| cases.csv | 147942 | `8845e329911d59a7ab7a3a183732c5cfd3d53645177ebf7cb636933a597cf20a` |
| batches.csv | 3375 | `a0a1e58dd4451b34d047559b51fb17671431ecdf438ec2b081d79910d4ba2cd3` |
| manifest.json | 10041 | `44f4d707fba4eb1e07545cfb640188fe76d55de848924b12773214332b1453d2` |

Only these code-owned invented inputs were exercised:

| Identity | Input SHA-256 |
| --- | --- |
| intake_workflow.fixtures.synthetic_payload (8 cases, original UTF-8 slices) | `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb` |
| editorial_demo.revision_fixtures.REVISION_HISTORY_RECORD (serialized intake, 1 case) | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` |
| batch_fixtures: synthetic-csv (4 parsed rows) | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| batch_fixtures: synthetic-json (4 parsed rows) | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| batch_fixtures: synthetic-jsonl (3 parsed rows) | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| batch_fixtures: synthetic-malformed (0 rows, MALFORMED_INPUT) | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

PostgreSQL is unavailable: normal `runserver` migration preflight failed during UI
inspection. No database-backed acceptance or owner source ZIP acceptance is
claimed. Services/tests/CLI do not need a database; no schema or migrations changed.

One independent final review covered every changed file and the authoritative
upstream services. No blocking correctness, security or requirements issues were
found; independent build/replay confirmed 20 cases, 4 batches and 303,490 bytes.
Its only optional suggestion was direct OS-level symlink/reparse rejection tests;
those branches were inspected but are not claimed as runtime-tested here. The
reviewer made no edits and did not rerun historical suites. No product code changed
after review.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD.**
