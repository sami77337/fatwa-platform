# Source-grounded fiqh reading trail

Pure, read-only navigation for one explicit source work and edition. This adds
no HTTP route, model, app registration, migration, database write or deployment.
It labels every result `SOURCE_BOOK_TOC_NOT_FATWAS`: a technically verified book
heading is neither a published fatwa nor a scholarly approval.

## Contracts and use

```python
from apps.fiqh_reading_trail import ReadingTrail

# Both dependencies are explicit. No fallback catalog or edition discovery.
trail = ReadingTrail(prepared_catalog, edition_id=7001)
result = trail.navigate(source_row_id=2, catalog=read_only_catalog)

# Retain the exact research occurrence while moving within the same edition.
result = trail.from_reference(
    case_triage, reference_ordinal=1, catalog=read_only_catalog, source_row_id=2
)
```

`prepared_catalog` uses the existing `apps.reference.records.PreparedCatalog`
contract. Construction reruns `prepare_catalog`, verifies its canonical checksum,
and validates full source pins through `SourceIdentity`. It rejects duplicates,
missing parents, cycles, invalid depth/count/order, forged checksum, unsupported
book identity and noninteger IDs. The limit remains 20,000 rows and depth five.
The resulting index and all public result objects are immutable.

The prepared catalog is caller-supplied authoritative topology. Its checksum
detects internal alteration; it does not authenticate an archive or demonstrate
owner-source acceptance. No owner archive is opened or validated by this service.
The existing `ReadOnlyCatalog` exposes original title paths, not ancestor IDs or
source order. Exact parent ID edges and ordering therefore come from the prepared
records; title equality cannot independently prove those edges against a live
database, particularly when ancestor titles repeat. Source hashes remain caller
assertions until the source input is independently validated.
The pure service has no database default: callers must explicitly provide the
existing `ReadOnlyCatalog` protocol, such as `SnapshotCatalog`. A separately
injected adapter's I/O remains the caller's responsibility.

`navigate` returns a `TrailResult` containing:

- `current`, exact root-to-current `breadcrumbs`, `previous`, and `next`.
- On each `TrailItem`: complete `Heading` evidence, edition-scoped catalog URL,
  existing escaped citation, exact source ID, parent row ID, depth, position and
  source order. Evidence retains original work/title/path text, printed part/page,
  numeric edition/row IDs, source namespace/book, edition key and both SHA pins.
- An edition-scoped catalog return link, `/fiqh?edition=…`.
- From research only, a local return link to the original case and reference
  ordinal, `/dev/research-bridge/<case>#reference-<ordinal>`.

Traversal is the complete edition's ascending, unique `source_order`, matching
the existing catalog source-order convention. IDs, titles and printed pages do
not determine neighbors. Source order is not reinterpreted as depth-first order.
First/last headings have a `None` neighbor; there is no wrapping. Duplicate titles
remain different headings with different parent IDs and links. Breadcrumbs are
derived exclusively from exact parent edges, including the current node.

The existing resolver checks each exposed heading against the independent
catalog. Full heading equality then checks all source pins, unchanged text, path
and printed location against the prepared topology. Ancestors of neighbors are
checked too. Catalog evidence with bool/float identities is rejected explicitly.
One call performs at most 15 distinct lookups, or 20 with a research origin;
lookups are deduplicated within the call and no edition scan is performed.

`from_reference` first uses the existing `research_bridge.bridge_reference` gate.
An upstream verified label alone is insufficient. The original reference must
match both catalog evidence and this trail's topology, even when the current
target has changed. The checked origin is reused within the invocation, avoiding
a second inconsistent origin lookup. Case keys and reference ordinals are bounded
and validated; no caller-provided return URL is accepted.

Any missing, ambiguous, unavailable, changed or unverified evidence closes the
whole response: `status="unverified"`, a stable reason, empty breadcrumbs and no
items, citations or links. It never skips an unverifiable immediate neighbor or
searches for a replacement. Invalid construction raises `ValueError`; unknown or
invalid navigation IDs return a closed result. Adapter programming errors are
not disguised as successful navigation.

## Synthetic offline demonstration

```text
python -B -m tools.fiqh_reading_trail --synthetic-fixtures-only
python -B -m unittest tests.fiqh_reading_trail.test_services
```

The CLI uses fabricated fixtures only. Source pins are synthetic assertions;
tests do not claim PostgreSQL-backed or owner-source acceptance. The service
performs no network calls, uploads, source modification, private-data operations,
grants, scholarly approval or publication. It does not add browser integration;
its generated catalog/research URLs target the existing routes.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED / GATES_HOLD.**
