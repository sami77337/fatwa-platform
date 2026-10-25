# لوحة التحرير الاصطناعية المحلية

Route: `http://127.0.0.1:8012/dev/editorial-dashboard`

Run with the existing Python 3.13 environment and pinned project dependencies:

```powershell
python -m apps.editorial_demo
```

This reuses the existing loopback preview server and skips its unrelated database
migration preflight. The dashboard composes FAST3's `build_queue_catalog`, `build_investigation` and
`diagnose_batches`; it does not store data or introduce editorial actions. Host and
peer must both be loopback, production profiles are denied, and only GET/HEAD are
accepted. No app registration, migration, dependency or settings change is needed.

## Metric meanings

- All rows: includes rejected inputs; **20** in the fixed fixtures.
- Questions: nonblank question text; **17**, preserving the original text for display.
- Prepared records: existing `case.record` objects; **6**, including original fixtures.
  This does not claim editorial completion, scholarly approval or publication.
- Preparation/display status comes exclusively from the workbench: **4 ready,
  4 review, 12 blocked**. Each metric opens the matching queue.
- Technical attention: status is not ready OR references are not all technically
  verified; **17 distinct rows**. This is a presentation predicate, not a new state.
- Reference counts: **15 occurrences** (8 verified, 7 unresolved, 0 mismatched).
  Missing references is a separate count of **8 records**, not reference occurrences.
- Source diagnostics cover only the four prepared synthetic inputs. Availability
  comes from explicit keys in the existing trusted synthetic reference map
  (`W7-SOURCE`), not incoming pointers: **1 missing-source occurrence**, **3 rows
  without a valid source pointer**, and 0 unspecified-inventory occurrences.
  Inventory membership is not evidence of scholarly or reference validity.
- Offline diagnostic preparation has no resolver. Its findings remain separately
  labeled and never replace the resolved workbench's status or decisions.

Batch selection scopes metrics and records; the batch overview always shows all
five queue groups, including the malformed input with zero rows. Original queue
grouping combines two investigation groups, so its reference metrics are plain
counts; exact case investigation links remain available. All case navigation uses
the case key rather than potentially duplicated external identifiers. Every row
links to its queue, workbench, investigation and HTML case packet.

The composition checks service identity and input hashes before rendering; a
mismatch returns a recoverable 503, never partially reconciled counts. Arabic,
whitespace, CRLF and combining characters are escaped and retained. There are no
remote assets, media downloads, user-selected files or database operations here.

## Inputs and verification

Base: PR #106, `codex/20261025-fast3-integration-pc2`,
`a149b39bfd624e330762459a7c3e0b4febc7187b`.

Built-in fixtures only (no owner archive acceptance):

| Input | SHA256 |
| --- | --- |
| Wave7 synthetic payload | `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb` |
| Serialized history intake | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` |
| synthetic-csv | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| synthetic-json | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| synthetic-jsonl | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| synthetic-malformed | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

Focused tests:

```powershell
python manage.py test tests.editorial_dashboard.test_dashboard tests.editorial_dashboard.test_browser --settings=config.settings.test
python -m ruff check apps/editorial_dashboard tests/editorial_dashboard
python -m ruff format --check apps/editorial_dashboard tests/editorial_dashboard
python manage.py check --settings=config.settings.development
```

Tests use actual synthetic services with database access forbidden. Chrome tests
exercise RTL/mobile layout, keyboard filters, exact source text and local read-only
navigation. PostgreSQL acceptance and protected owner archives are outside this
dashboard verification; no success is claimed for them. Revert the new directories
and the single route include to roll back; no data conversion is required.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD.** No privileged actions, publication or scholarly approval.
