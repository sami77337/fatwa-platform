# Verified catalog navigation adapter (development only)

The existing `ReadingTrail` already computes ancestors and immediate neighbors in
original source order. This adapter adds the missing check between its independent
`PreparedCatalog` contract and a live Django catalog: every edition/work field,
row, parent identity, printed-location identifier and stored ingest checksum must
match before any title, edition metadata or link is returned. A different row in
an unrelated branch also closes the result. Titles are never searched or normalized
to infer an identity. A catalog heading remains `SOURCE_BOOK_TOC_NOT_FATWAS`.

`CatalogNavigation` reuses `reference.query.bounded_int`, `ReadingTrail.navigate`
and `ReadingTrail.from_reference`; the latter rechecks the existing research bridge
on each call. `DjangoNavigationReader` reuses source-pinned reference models,
`reference.services.resolve_edition` and `DjangoCatalog` for heading evidence.
The new code does not implement a second traversal or scholarly citation resolver.

## Integration interface

```python
from apps.fast8_fiqh_navigation.services import CatalogNavigation
from apps.fast8_fiqh_navigation.django_adapter import DjangoNavigationReader

# prepared is a separately supplied, trusted PreparedCatalog, never inferred
# from the database under examination. edition_id is explicitly pinned.
navigation = CatalogNavigation(prepared, edition_id)
result = navigation.navigate(
    {"edition": str(edition_id), "source_row_id": "40"},
    DjangoNavigationReader(),
)
# For a fixed synthetic research occurrence:
# result = navigation.from_reference(query, case, ordinal, reader)
```

Only a verified result exposes `edition_title`, `publisher`, and the existing
`TrailResult` (current heading, root-to-current breadcrumbs, previous/next and
return URLs). Closed results expose no source metadata or links. A missing reader
returns `NOT_CONNECTED`. No default catalog, edition discovery, source loader,
route, view, model, migration or HTTP write endpoint is added. Renderers must
escape original text as usual; original strings are not HTML-safe markup.

The PostgreSQL reader must run outside another transaction with autocommit on.
It starts one `REPEATABLE READ, READ ONLY` transaction covering the full topology
check and every evidence read. It rejects other backends and non-default ORM
read routing. The row scan is bounded at the declared count plus one (maximum
20,001); it is deliberately not cached, so changed order/parents cannot reuse a
previously verified trail. This is O(N) per request and is not a production latency
claim. The caller must configure connection timeouts and a suitable read-only
development connection. No database operation is performed at import/construction.

## Reproducible synthetic check

```powershell
python -B -m tools.fast8_fiqh_navigation --synthetic-fixtures-only --source-row-id 40 --from-reference
python -B -m unittest discover -s tests/fast8_fiqh_navigation -p "test_*.py" -v
python -B -m unittest tests.fiqh_reading_trail.test_services tests.research_bridge.test_services -v
```

The CLI uses existing fabricated `fast7c-reading-trail-synthetic-v1` (nine rows,
two roots, depth five), canonical fixture SHA-256
`b1abc9c56a6173f8c7c2f573af746aaee6140aaea58df26b6ffebd7803e12d98`.
The `a...` archive pin and `b...` input pin are fabricated assertions, not hashes
of owner source archives. No real source files are opened or copied. CLI output
states `database_catalog=NOT_RUN`, `owner_archive=NOT_SUPPLIED`, and
`source_acceptance=NOT_RUN`; a verified synthetic result does not override them.

Local PostgreSQL acceptance is `NOT_RUN`: Docker engine is unavailable and no
PostgreSQL listener was available on loopback 5432. ORM boundary tests use mocks,
not a substitute PostgreSQL backend. Three explicit PostgreSQL tests are supplied
outside offline discovery. With an already configured isolated PostgreSQL test
connection, use:

```powershell
$env:PGTESTDATABASE = 'test_fast8_fiqh_navigation_synthetic'
python -B manage.py test tests.fast8_fiqh_navigation.postgresql --settings=config.settings.test --noinput --verbosity=2
```

Discovery refuses a different test database name before database creation or
migrations; test setup also checks the connected database name before synthetic
fixture writes. These tests are not claimed as passed without PostgreSQL.
Browser acceptance is `NOT_RUN` for this
adapter: no UI or routes were added. Existing B6/C6/D6 CI remains unchanged and
does not automatically register this new lane's tests; use the focused command
above when integrating. Exact commit/CI evidence belongs in the Draft PR.

The first standalone unit invocation exposed a test setup error: constructing
`QueryDict` required settings. The duplicate-query test now supplies only its
request-parser setting locally; no product validation or assertion was removed.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No role grants, policy changes, scholarly answers,
approval, publishing, account operations or external content services.
