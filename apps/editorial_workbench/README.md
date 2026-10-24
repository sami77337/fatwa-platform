# Connected editorial workbench

Development only; synthetic data; no database or HTTP mutations.

## Multi-batch bridge (2026-10-24)

The workbench now consumes `prepare_batches` from PR #95 at exact source commit
`5530b9f9b425d52790ce2072e1b0b6c30bd447df`. Its parent was already an ancestor of
the PR #96 base `b1653b20584052f36fba1b59565c7ed57d688215`; neither the source
commit nor its patch was contained. It was cherry-picked with `-x` without
conflicts as `0bcbc31` (stable patch ID
`e9ff38802af013c420f635440bc7844dc8ef00d0`). The integration PR targets PR #96's
branch, `codex/20261024-fastbuild-editorial`, not `main`.

Open `/dev/editorial-workbench?batch=synthetic-csv` to select a prepared batch.
Eleven additional rows across CSV, JSON and JSONL include valid receipts,
pending inputs, cross-batch duplicate identities, invalid media/references,
CSV overflow cells and null records. A fourth malformed file remains visible
with its digest and recovery instructions, without fabricated rows. Existing
Wave7 cases and the independent revision-history sample remain available.

Each row is addressed by batch identity and original ordinal. The bridge checks
batch hashes, freshly parsed original fields, row order and exact serialized
draft association before displaying results. Rejected inputs have no draft;
missing media remains pending without history. Pending reference mapping can
have its own receipt draft. Receipt validity and reference verification are
displayed independently; no references or scholarly citations are invented.
Only a single empty `received` snapshot is created by preparation. Neighbor
navigation discards revision selection from the previous record and preserves
batch/search/status filters. Existing comparison/history/audit services remain
responsible for the selected record's own snapshots.

The new inputs are fixed UTF-8 bytes generated in memory by `batch_fixtures.py`.
There is no upload, file-path parameter, network fetch, write endpoint, database
operation, or new permission. Full original file text and its byte digest are
available separately from explicitly labeled JSON serialization of parsed row
fields. CSV CR/LF and Unicode values survive in the DTOs; browsers may normalize
line endings when rendering HTML. No original byte offsets are claimed for
these parsed rows. Recovery instructions require correcting the synthetic
fixture outside the read-only UI and preparing it again.

Templates are local to `apps/editorial_workbench/templates/`, rendered with the
existing Django backend and fixed code-selected names. The workbench template
adapts PR #96's presentation and reuses its base/comparison fragments. Shared
templates, URL configuration, settings and dependencies are unchanged by the
bridge. Keep future shared workbench layout changes synchronized with this local
copy. Removing these bridge changes restores PR #96 behavior; no migrations exist.

Fixed source identities (SHA-256):

| Batch | Format | Bytes | Digest |
| --- | --- | ---: | --- |
| synthetic-csv | CSV | 719 | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| synthetic-json | JSON | 620 | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| synthetic-jsonl | JSONL | 714 | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| synthetic-malformed | invalid JSON | 13 | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

Focused bridge command (33 tests, including the 25 existing workbench tests):

```powershell
python manage.py test tests.editorial_workbench.test_batches tests.editorial_workbench.test_services tests.editorial_workbench.test_views tests.editorial_workbench.test_persisted --settings=config.settings.test --noinput
```

The 8 new tests first failed on the missing bridge and batch navigation, then
passed against the real preparation/HTTP/history services. They cover isolated
rows and histories, rejected duplicates, missing media, source hashes, Unicode,
reference positions, recovery details, corrupted service reports, deterministic
fresh results and forbidden external I/O. `SimpleTestCase` forbids database
access; this is not PostgreSQL or owner-source acceptance.

Final validation: 33 workbench + 65 prepared-pipeline + 40 content-intake +
8 intake-check + 45 directly affected editorial-demo tests passed (191 total,
no failures or skips). Django development system check, bridge-only Ruff lint
and format (13 Python files), and Git whitespace checks passed. One independent
read-only final review reran the 33 workbench tests after the missing batch
selector was corrected and found no remaining actionable issues.

An expanded Ruff check also inspected inherited intake tests: five existing
import-order findings remain in `test_exact_prepared.py`, `test_intake.py`,
`test_pipeline.py`, `test_source_pins.py` and `test_wave6_contract.py`; the expanded
format check identified three inherited prepared-pipeline test files. They were
not reformatted outside this lane. No browser layout, PostgreSQL or owner archive
acceptance is claimed for this bridge.

## Original PR #96 implementation notes

Run the existing database-free local preview launcher, `python -m apps.editorial_demo`,
and open <http://127.0.0.1:8012/dev/editorial-workbench>. The launcher skips only
the unrelated migration preflight; it preserves middleware and development guards.
The ordinary Django `runserver` also works when the configured PostgreSQL server
is available, but performs its usual migration preflight before serving.

Implementation plan: reuse the exact immutable history fixture and existing
Wave7 payload, pipeline, reference diagnostics, history/comparison and revision
audit services; preserve each case's identity and provenance; connect them with
Arabic SSR GET navigation. Build adapter tests, HTTP/guard tests, accessible RTL
templates, then run the new tests and one independent final review.

The history sample and the eight Wave7 input rows are separate cases. A missing
draft never borrows another case's snapshots. Automatic receipt is not human
review. Numbered snapshot observations are not authenticated workflow events.
The fixed synthetic TOC is asserted fixture evidence, never an inspected archive
or scholarly verification. Source text, source byte offsets and hashes are
displayed without rewriting it. Serialized history intake provenance is labeled
separately from original Wave7 byte slices.

The optional `/dev/editorial-workbench/workflow-audit` route calls the existing
Wave7 guarded reader and timeline builder. It remains unavailable unless the
existing Wave7 profile, read flags and owned synthetic database are configured.
The workbench does not turn them on, seed data, initialize a database or open a
write transaction. Stored rows are not linked to snapshots by external ID.

Integration handoff: `config/urls.py` changes only the `include` import and one
namespaced include at `dev/editorial-workbench`. Keep it before generic preview
detail routes. `config.wave7_urls` inherits this include already; no app
registration, models, migrations, dependency or settings changes are needed.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED. No approvals, publication, privileged grants or owner-source writes.

Validation (2026-10-24): 25 new tests pass, including HTTP rendering and guard
integration, with database access forbidden by `SimpleTestCase`. Run:

```powershell
python manage.py test tests.editorial_workbench.test_services tests.editorial_workbench.test_views tests.editorial_workbench.test_persisted --settings=config.settings.test
python manage.py check --settings=config.settings.development
python -m ruff check apps/editorial_workbench tests/editorial_workbench config/urls.py
python -m ruff format --check apps/editorial_workbench tests/editorial_workbench
```

An independent read-only reviewer reran those 25 tests and reported no actionable
findings. Chrome QA exercised case navigation, reverse comparison 11 → 4 by
keyboard submission, search empty-state recovery, valid fragment targets, and
320/375 px layouts without horizontal overflow. No historical suite was rerun.
PostgreSQL was unavailable locally (ordinary `runserver` migration preflight
timed out); persisted-reader tests use immutable DTOs, not database acceptance.

Exact synthetic input identities:

- `fixtures.synthetic_payload()` (Wave7 original UTF-8 bytes): SHA-256
  `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`.
- `serialize_intake((REVISION_HISTORY_RECORD.intake,))` (explicit serialization,
  not owner source bytes): SHA-256
  `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0`.

Source ZIPs and book 622 owner-source acceptance were not exercised. No migrations
are introduced; rollback consists of removing the include and the new modules.
