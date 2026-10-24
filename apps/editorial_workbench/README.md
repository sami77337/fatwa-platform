# Connected editorial workbench

Development only; synthetic data; no database or HTTP mutations.

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
