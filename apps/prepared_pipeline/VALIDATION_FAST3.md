# FAST3 preparation validation — 2026-10-24

Verified parent: `codex/20261024-fast2-integration` at
`e64ebc0d219f975eb7be96042a4e8761b1a0e6e9` (local merge-base and remote head agree).
Development branch: `codex/20261024-fast3-preparation`.

Python 3.13.15. Final focused and affected checks:

| Command | Actual result |
| --- | --- |
| `python -m unittest discover -s tests/prepared_pipeline` | 79 passed |
| `python -m unittest discover -s tests/content_intake` | 54 passed |
| `python manage.py test tests.editorial_workbench.test_batches tests.editorial_demo.test_synthetic_batch --settings=config.settings.test --noinput` | 19 passed; system check clean |
| Ruff check/format on new app/test Python files | Passed |
| Isolated Ruff check/format on new tool Python files | Passed |
| `git diff --check` | Passed |

152 tests total. These are offline unit/command tests and database-free Django
`SimpleTestCase` consumers. PostgreSQL, owner source ZIP acceptance, real/private
workflows and broad historical suites were not run or claimed. No migrations.

Committed synthetic fixture identities (UTF-8 with LF, pinned by local attributes):

| Fixture under `tools/content_intake/examples/` | Bytes | SHA-256 |
| --- | --- | --- |
| `synthetic-batch-a.csv` | 381 | `123c6f5449df6450baa780bec12e9d7d93d02c277700940ded9ee2df6e1875d4` |
| `synthetic-batch-b.jsonl` | 396 | `584facf57bde2ab1f94ee49ef57ff1f1155d5e5beac0a91f124d12338cd98e63` |

Ran the documented two-fixture command with expected batch IDs `a`, `b` and source
inventory `synthetic-source-a`, exported to a temporary new directory and checked
the bundle against a second full processing run. Both commands returned the
expected exit 1 for deliberately blocked rows, and stdout matched byte for byte.
Actual totals: 4 records, 1 receipt, 3 blocked rows, 1 cross-batch duplicate group,
1 missing source, 0 malformed files and 0 missing batches.

| Export | Bytes | SHA-256 |
| --- | --- | --- |
| `diagnostics.json` | 9552 | `e71a375b40e3778a9eeec8ca77f1b301fbcf3f237209aba99747509c8a9fc445` |
| `rows.jsonl` | 6771 | `7fc57835ab24916b744c88065f70bb11b6c45ea758af40f4f0901abd40ae12ae` |
| `recovery.txt` | 2799 | `62e45df9c0372e95eeead7ef030f40753c72650dd5a08dab8a1f334d95ebc667` |

Independent final reviewer inspected the implementation and ran focused tests and
lint. One finding: bundle checking initially used an unbounded file read. Fixed
with an expected-byte-length-plus-one read and a regression test. Reviewer
rechecked the fix and row navigation; no remaining actionable findings.

Existing input/preparation contracts and GET/HEAD/loopback guards remain intact.
No source mutation, automatic correction, trusted mapping inference, public upload,
publication, scholarly approval, database write or deployment is introduced.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED.
