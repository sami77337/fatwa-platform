# C3 library contract

This library resolves staff-proposed editorial pointers to immutable TOC headings.
It never associates question text with a reference and never produces ruling text.
It has no persistence, network client, media processor, routes or Django app registration.

## Input and identity

`resolve(link, catalog)` accepts a mapping with required positive integer `edition_id`
(the existing catalog edition database PK) and `source_row_id` (original source row).
`public_node_id` is an alias for the existing public API node ID, which is that same
source row ID, not the heading database PK or source_id string. If both are supplied,
they must agree. Values are bounded to signed 64-bit positive integers; strings,
bools and null are rejected. No default edition is selected.

Optional `work_title`, `heading_title`, `printed_part` (strings), and `printed_page`
(positive integer) are exact assertions against source evidence. Omission means no
assertion; explicit null is invalid. No trimming, Unicode normalization, case folding,
or Arabic spelling normalization is applied. Unknown fields produce unverified.
Unicode strings must encode as strict UTF-8 and contain no ASCII controls.

Example:

```python
from apps.reference_links import resolve, render_citation
from apps.reference_links.django_adapter import DjangoCatalog

result = resolve({"edition_id": 1, "source_row_id": 7}, DjangoCatalog())
internal = result.internal_payload()
if result.outcome == "verified":
    citation = render_citation(result)
```

The IDs above illustrate the interface only; they do not assert any source mapping.
`render_citation` returns HTML-escaped text, without safe-marking. In Django SSR,
normal autoescaping is safe but may double escape; choose a rendering integration
carefully and do not safe-mark arbitrary source metadata. No template is wired here.
The citation contains the work title, complete heading path, printed part/page and an
explicit TOC disclaimer. Edition/publisher/internal IDs are not appended to public wording.
Internal `toc_url` uses the existing `/fiqh/nodes/{source_row_id}?edition={edition_id}` route.

## Adapter

`ReadOnlyCatalog.lookup(edition_id: int, source_row_id: int) -> Sequence[Heading]`
returns zero, one or at most two immutable records. Two indicate ambiguity, even when
one happens to match supplied metadata. Do not filter candidates by title or page.
Adapters must establish a complete root-to-target path in source order, preserve original
text and authoritative location, scope every row to the exact edition, and raise
`CatalogReadError` when evidence cannot be read reliably. Unexpected programming errors
are not swallowed. The resolver checks returned identity, path termination and bounds,
required text and SHA syntax; adapter implementations remain responsible for source truth.

`SnapshotCatalog` freezes a caller-supplied sequence of `Heading` records into a bounded
index (20,000 input rows maximum), retaining at most two candidates per exact identity.
It performs no loading or importing. The caller must identify and trust its snapshot
provenance; a syntactically valid SHA is not independent proof of authenticity.
`Heading.path` must be an immutable tuple including the target, maximum five titles.

`DjangoCatalog` delegates exclusively to existing `resolve_edition`, `node`, and
`heading_path` read services. Existing services validate ancestor edition, depth and
cycles. It uses work.title_original for attribution, source_part/source_page_number
for printed location, and source_input_sha256 for provenance. It never calls save,
create, update, delete, migrations or ingestion. Real PostgreSQL integration is NOT_RUN.

## Outcomes

| Outcome | Meaning |
|---|---|
| verified | Exact unique identity and complete source evidence, supplied assertions agree |
| not_found | No row for the exact edition/identity |
| ambiguous | Multiple candidates; no automatic selection |
| mismatched_metadata | Supplied exact metadata differs; field names reported, no citation rendered |
| unverified | Missing/invalid input, unavailable catalog, adapter violation or incomplete evidence |

Only verified results can render a citation. Missing source part/page is unverified.
Internal incomplete-location evidence may be retained for staff diagnosis; it is not a
publishable citation. Verification establishes catalog identity only, not relevance to
the question, correctness of a ruling, editorial acceptance or publication permission.

## Prepared intake

`resolve_intake(raw: bytes, catalog)` handles the reference-links portion of
`fatwa.prepared-intake.v1`. Maximum 2,000,000 bytes, 1,000 items, 100 links per item.
It returns external IDs with a list of typed Resolution objects. It rejects malformed
JSON, duplicate keys/external IDs, invalid UTF-8, unknown schema, and null/non-list
reference_links. Missing reference_links means an empty list; no reference is inferred.
Invalid individual link objects are unverified. Envelope errors raise ValueError.
Question, prepared_clip_url and staff_notes remain opaque; the staff-intake owner must
validate their own fields. No URL is opened or fetched. Nothing in this API authorizes
publication, grants access, or approves prepared records.

Run synthetic tests with `python -m unittest discover -s tests/reference_links -v`.
See RESULT_AR.md for actual results and limitations.
