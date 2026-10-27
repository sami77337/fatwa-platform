# FAST9 case-to-source technical evidence join

Development-only, synthetic, read-only. No URL, UI mount, model, migration,
network source access, or persistence is added. Base FAST8 Draft PR #151:
`0769f66e93fdf710ca55e9e68e87430a93f14c40`.

## Contract and result

`join_case_source(request, packet, prepared=..., reader=...,
synthetic_fixtures_only=True)` selects the original fixed case from
`reference_triage.build_investigation`. It reuses FAST8 case-reference `_bind`
to compare the complete canonical packet, then reparses the original UTF-8
input with the existing intake contract. It checks the exact case-row slice,
original reference occurrence/ordinal, packet/row/occurrence SHA256, verified
source identity, opaque source ID, numeric edition/row, work, printed location,
and independently supplied catalog checksum. FAST8 `CatalogNavigation` checks
the complete live topology and reference evidence within one reader snapshot.
The successful result is returned only after the snapshot exits successfully.

- `VERIFIED_TECHNICAL`: all supported synthetic technical contracts match.
- `NOT_CONNECTED`: missing catalog/source contract, unknown case, absent or
  unresolved occurrence, or unsupported prepared-case original-byte adapter.
- `REJECTED`: stale/cross-case/tampered evidence or invalid contracts.

Closed results contain no partial join, citation or source metadata. Success
includes exact Arabic heading/path, printed part/page, full `HeadingRecord`,
edition metadata, original pointer, and byte-offset/hash provenance. Original
case/question/media/answer text is not exported. Numeric bool/float aliases do
not qualify as exact IDs. Inputs are not normalized, rewritten, or timestamped.

`row_sha256` is precisely the existing `CaseTriage.source_sha256`, also
`packet.source.text_sha256`: SHA256 of the case row's original UTF-8 text.
`HeadingRecord` has **no original source-book row-byte SHA field**. This lane
does not invent one: the existing `PreparedCatalog.checksum` pins every catalog
record field. No claim of original owner-source row-byte verification is made.

The old reading-trail fixture uses `synthetic-1`, while the actual case identity
requires `wave7-title-1`; it is rejected, despite matching titles/numeric IDs.
The new explicitly fabricated three-heading fixture uses the existing Wave7
source identities. Its `a…a`/`b…b` source pins are synthetic assertions, not
archive hashes. Wave7 omits `original_identity` in its diagnostics; the original
pointer is recovered only from its validated original UTF-8 slice.

The service accepts only existing code-selected synthetic cases. It does not
accept uploaded data or establish connections for real/private cases or owner
sources. `owner_source=NOT_CONNECTED`, source/scholarly acceptance `NOT_RUN`
remain true even on a successful synthetic join.

## Commands and actual results (2026-10-27, Python 3.13.15)

From repository root, no Django setup or database is needed:

```powershell
python -B -m unittest discover -s tests/fast9_case_source_join -p 'test_*.py' -v
```

Actual: **23 tests passed**, no skips/xfails. Includes 15 service tests, 5 real
CLI subprocess tests, and 3 offline PostgreSQL preflight tests.

```powershell
python -B -m unittest tests.fast9_case_source_join.test_services tests.fast9_case_source_join.test_cli tests.fast9_case_source_join.test_preflight tests.fast8_case_references.test_services tests.fast8_case_references.test_cli tests.fast8_fiqh_navigation.test_services tests.fast8_fiqh_navigation.test_cli tests.fast8_fiqh_navigation.test_django_adapter tests.fast8_fiqh_navigation.test_preflight tests.fiqh_reading_trail.test_services tests.fiqh_reading_trail.test_boundaries tests.editorial_workbench.test_packets tests.research_bridge.test_services tests.reference_links.test_resolution tests.reference_links.test_bridge
python -m ruff check --no-cache apps/fast9_case_source_join tools/fast9_case_source_join tests/fast9_case_source_join
python -m ruff format --check --no-cache apps/fast9_case_source_join tools/fast9_case_source_join tests/fast9_case_source_join
```

Actual: **160 new/affected offline tests passed**, zero skips; lint/format passed.
This is a focused suite, not the whole repository suite. Unbounded discovery
could run database/browser suites without the required synthetic prerequisites.

```powershell
python -B -m tools.fast9_case_source_join --synthetic-fixtures-only
python -B -m tools.fast9_case_source_join --synthetic-fixtures-only --catalog synthetic
python -B -m tools.fast9_case_source_join --synthetic-fixtures-only --catalog synthetic --case-key intake-7
```

Actual: default catalog absent => `NOT_CONNECTED`, exit 2; explicit synthetic
catalog => `VERIFIED_TECHNICAL`, exit 0; second original case => row 2/page 8.
CLI is deterministic JSON; the service retains literal UTF-8, while the CLI
escapes Unicode for portable Windows output without changing decoded text.
No paths, uploaded packets, source mappings or database options are accepted.

Fixture: `fast9-case-source-join-synthetic-v1`.
Canonical fixture SHA256:
`49d89794c07c153399134ad02e79b31517f17cb5c53f02f22fe82e625eb564dc`.
Catalog checksum:
`bee2ceb3943a9c3ea1ebc5809fb08a7d482d621f6132cd09d07d5e5df58af702`.
Original Wave7 input SHA256:
`cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`.
Original intake-1 row SHA256:
`9997733aafa7ef2daf20e944fecf31a5057d4c8d48b0575ecdc1fc26b7c96a09`.

Test-first runs failed while the service/CLI modules were absent. The first
service implementation also rejected valid originals because the diagnostic
`original_identity` was empty; reading the actual source-slice contract fixed
this. Two initial lint findings (unused import/import order) were corrected.
No remaining failures in the executed focused suite.

Independent final read-only review: a separate GPT-6 Astra agent inspected the
complete implementation, contracts and guarded runner and independently ran all
23 offline tests. No critical, important or minor correctness findings; no files
changed by the reviewer. PostgreSQL remained NOT_RUN during review.

## PostgreSQL: NOT_RUN locally

No preauthorized disposable target was supplied in this session. No credentials
were discovered, no database was connected to, and no migrations were run.
Browser tests: NOT_RUN (no UI in this lane). Owner source acceptance: NOT_RUN.

The opt-in command is:

```powershell
python -B -m tools.fast9_case_source_join.postgresql
```

Without explicit prerequisite environment it prints `postgresql=NOT_RUN` and
exits 2 before Django setup. A provisioner must separately authorize and prepare
an owned synthetic base with the existing schema/ownership markers. This lane
does not claim/initialize a base or create roles. Required environment:

| Variable | Exact value |
|---|---|
| DJANGO_SETTINGS_MODULE | config.settings.wave7_test |
| FATWA_PRODUCTION | 0 |
| FATWA_WAVE7_SYNTHETIC_WRITES | 1 |
| FATWA_WAVE7_SYNTHETIC_READS | 1 |
| FATWA_FAST9_CASE_SOURCE_JOIN_PG | 1 |
| PGHOST | 127.0.0.1 |
| PGDATABASE | wave7_synthetic_fast9_case_source_join |
| PGTESTDATABASE | test_wave7_synthetic_fast9_case_source_join |
| PGUSER | wave7_synthetic |
| PGPORT | Explicit authorized port, 1–65535 |
| PGPASSWORD | Explicit synthetic credential supplied by provisioner |

Connection overrides are rejected. Existing `require_synthetic_write` checks
the actual database, role, PG 17/18, ownership and schema before data creation.
Only the existing `Wave7TestRunner` creates/migrates its fresh exact test DB;
it refuses reuse and cleans up only the test DB it created. No new schema or
migrations. The two opt-in tests insert only this fabricated fixture after
rechecking actual test identity, then exercise the real read-only reader and
assert no SQL writes during joins. These two tests have **not run locally**.

## Integration and governance

Only lane-owned files change. Existing B6/C6/D6 workflows do not collect the new
modules; their green status would not be FAST9 test coverage. The coordinator
must explicitly add these modules and provision/authorize PG before claiming
that coverage. No public endpoint is added and no shared URL mount is needed.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. No owner, catalog-policy,
scholarly, production or release acceptance is inferred.
