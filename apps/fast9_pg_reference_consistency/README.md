# FAST9 pinned ORM catalog consistency

Development-only adapter, independently based on FAST8 PR #151 at
`0769f66e93fdf710ca55e9e68e87430a93f14c40`. Changes stay in this lane's three
owned folders. No existing service, settings, route, schema, migration, CI,
source archive or original record file is modified.

Inspected contracts: `apps.reference.models`, `apps.reference.records`,
`apps.reference.ingest`, `apps.reference_links.django_adapter`, and
`apps.fast8_fiqh_navigation`. The ingest contract already pins original fields;
FAST8 navigation reconstructs and hashes the topology but does not select the
stored `title_normalized`. This adapter checks that stored search projection too,
and compares actual parent PKs plus parent source-row and edition identities.
It neither replaces nor patches the existing services.

## Integration contract

```python
from apps.fast9_pg_reference_consistency.django_adapter import DjangoConsistencyReader
from apps.fast9_pg_reference_consistency.services import check_catalog

# trusted_prepared must be independently supplied, never reconstructed from
# the database being checked. Alias/edition are explicit integration inputs.
result = check_catalog(
    trusted_prepared, explicit_edition_id, DjangoConsistencyReader(using=authorized_alias)
)
```

Construction performs no I/O. Omit the reader for `NOT_CONNECTED`. Invalid pins,
unknown work/edition, wrong explicit edition, unavailable DB and nested/manual
transactions remain `NOT_CONNECTED`. An existing joined catalog with different
fields, absent/extra headings or ambiguous work/edition rows is `INCONSISTENT`.
Only a complete match returns `CONSISTENT`, checked row count and ingest checksum.
`source_acceptance` is always `NOT_CONNECTED`; this is row-consistency evidence,
never approval of a real catalog, source owner, scholarly policy or production.

Scope is one exact namespace/book and edition key. Other independently keyed
works/editions are outside the assertion and are allowed. All work and edition
metadata, declared counts, source hashes/input name, ingest checksum, heading
identities, sequence, sibling positions, depth, parent links, printed part/page,
entry number, original title and normalized search title are checked. Original
text comparisons preserve Unicode composition, whitespace and CRLF. Local PKs
are relational identities, not invented source IDs. `ingested_at` is not part of
the source contract; no write occurs and optional PG tests compare timestamps
before/after. The model has no individual row-SHA field; none is invented.

`DjangoConsistencyReader` uses the explicitly selected alias for every ORM query,
bypassing implicit router selection. It refuses non-PostgreSQL and outer
transactions. A fresh durable `REPEATABLE READ, READ ONLY` transaction contains
at most three bounded SELECTs: up to two matching works, two matching editions,
and independently pinned row count + one overflow heading (maximum 20,001).
Timeouts are transaction-local (statement 3s, lock 1s). Transaction exit must
succeed before results return. A tampered DB-declared count cannot expand reads.
The checker validates the independently supplied ingest checksum before I/O.
No repairs, seeding, public writes, URLs, or automatic integration are supplied.

## Fabricated fixture identity

- ID: `fast9-reference-consistency-synthetic-v1`
- Canonical JSON input SHA256:
  `52b1fb890be6800995125696cd2643f576e7ea1415cc30c412c4518ea393cbc2`
- Prepared ingest checksum:
  `bacfe72cb6a178ed1f93cec8925ac262ab02ae54ef712c2519bf4d94396aeec9`
- Four fabricated headings, two roots, depth two. Noncontiguous source ordering,
  duplicate display titles, decreasing printed page numbers, Arabic diacritics,
  a combining character, whitespace and CRLF exercise lossless comparisons.
- Archive SHA is the hash of the synthetic marker `synthetic-no-owner-archive`,
  **not** evidence that any owner archive was supplied or verified.

## Executed validation (2026-10-27)

Python 3.13.15, Django 5.2.18. Commands from repository root:

```text
python -B -m unittest discover -s tests/fast9_pg_reference_consistency -t . -v
python -B -m unittest discover -s tests/fast8_fiqh_navigation -t . -v
python -m ruff check apps/fast9_pg_reference_consistency tests/fast9_pg_reference_consistency tools/fast9_pg_reference_consistency --no-cache
python -m ruff format --check apps/fast9_pg_reference_consistency tests/fast9_pg_reference_consistency tools/fast9_pg_reference_consistency --no-cache
python -B -m tools.fast9_pg_reference_consistency --postgresql
```

Results: 34 new offline tests PASS, 32 affected FAST8 tests PASS, Ruff lint/format PASS.
No skips/xfails. Offline tests include pure contract corruption, mocked ORM
transaction/query limits, fail-closed connection/commit errors and preflight
guards. Seven actual PostgreSQL cases were **collected only** in a subprocess
with connections prohibited; none was executed. No browser run is claimed.

PostgreSQL command: exit 2,
`{"postgresql": "NOT_RUN", "reason": "EXPLICIT_SYNTHETIC_CONFIGURATION_REQUIRED"}`.
No preauthorized target configuration was supplied. No DB connection, discovery,
seeding or migration occurred. PostgreSQL acceptance remains **NOT_RUN**.
No failing assertions remain in the executed offline suites.

One independent read-only GPT-6 Astra reviewer reran all 34 offline cases with
database connections explicitly prohibited. Final review: no remaining actionable
findings after fixing stale configured/cached connection identity handling and
aligning unknown-edition status documentation. No reviewer DB access occurred.

The optional PostgreSQL suite ingests only this fabricated contract through the
existing ingest service, then checks actual ORM state, unchanged timestamps,
query bounds, server read-only enforcement, changes/missing/extra rows and
cross-edition parent collisions. Its positive case also calls existing FAST8
navigation and the reference evidence adapter. This is not an executed result.

Inherited B6/C6/D6 workflows do not register these new modules. Their status is
reported separately on the draft PR at its exact remote head; green inherited
CI is **not** new lane test coverage. Integration mounting/collection, actual PG,
real catalog/source-owner acceptance and policy acceptance remain unconnected.

See [guarded test command](../../tools/fast9_pg_reference_consistency/README.md).

Official state: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
