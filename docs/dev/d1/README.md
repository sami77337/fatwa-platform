# D1 local executable pipeline

Python 3.13, repository root; no new dependencies, Django setup, database or network needed.

```powershell
python -m apps.prepared_pipeline
python -m apps.prepared_pipeline --json
python -m unittest discover -s tests/prepared_pipeline -v
python -m unittest discover -s tests/content_intake -q
python -m unittest discover -s tests/fatwa_drafts -q
python -m unittest discover -s tests/reference_links -q
```

The CLI runs only its inline synthetic sample. It prints to stdout and has no file input/output option. Never redirect private staff content into artifacts. The library returns content in memory only; its synthetic acknowledgement is a caller obligation, not sensitive-data detection.

```python
from apps.prepared_pipeline import prepare_batch
batch = prepare_batch(raw, synthetic_fixtures_only=True)
records = batch.drafts                  # immutable C2 DraftRecord snapshots
report_bytes = batch.json_bytes()       # deterministic UTF-8, original text included
preview = batch.preview_ar()            # plain text, not trusted HTML
```

Input is strictly the C1 canonical JSON envelope `fatwa.prepared-intake.v1`: exactly schema/items, 1–1000 items, <=1,000,000 bytes and <=100 reference links per row. Duplicate JSON keys, nonfinite numbers, invalid UTF-8 and escaped lone surrogates are rejected. Envelope failures raise C2 ValidationError with no submitted content. Row errors produce findings and block that row; duplicate external IDs block all occurrences. C1 validation is reused, but original strings are retained without trimming or normalization. C2 validation additionally requires HTTPS finished media. C1 title fallback is supported; conflicting question/title is blocked. JSON-string reference arrays are rejected: canonical links must be an actual list.

Missing finished media yields `needs-editor-review`, preserving the entire original row, and no C2 draft: C2 requires a real clip URL. No placeholder URL is invented. Valid rows receive revision 1/action received/state received with empty answer/title and an explicit automated-receipt attribution. No human edit or workflow transition is simulated. C2 revision functions remain available on returned records and enforce expected revisions.

## Explicit mapping and trusted catalog

C1 opaque `(source_id, heading_id)` pairs are not C2 source identity or C3 numeric identity. No numeric parsing, edition selection, question matching or catalog search is attempted. Caller supplies a separate typed map keyed by the exact pair:

```python
from apps.prepared_pipeline import C1Pointer, ExplicitMapping
from apps.fatwa_drafts.intake import ReferenceLink
from apps.reference_links.resolution import Heading, SnapshotCatalog

# Entirely invented fixture identities; never a mapping for the real book-622 catalog.
source = ReferenceLink('synthetic', 'fake-book', 'fake-edition', 'a'*64, 'b'*64, 'opaque')
reference_map = {
    C1Pointer('opaque', 'not-a-number'): ExplicitMapping(
        source, 7, 9, 'PipelineTests.test_verified')
}
catalog = SnapshotCatalog([
    Heading(7, 9, 'عمل تجريبي', 'عنوان تجريبي', '1', 2,
            ('عنوان تجريبي',), 'synthetic', 'fake-book', 'b'*64)
])
batch = prepare_batch(raw, synthetic_fixtures_only=True,
                      reference_map=reference_map, catalog=catalog)
```

The input row must explicitly propose that pair. Tests `test_verified`, `test_exact_pair_required`, `test_mismatch`, `test_c2_compatibility` exercise this synthetic conversion. `test_identity` identifies the caller's conversion test; a string is not independent evidence that a test ran. Real conversions require separately supplied and tested source maps. No real map ships here. C2 edition_key/archive SHA/source_id have no equivalent fields in C3 evidence: their correspondence remains the explicit map provider's responsibility. Available namespace/book/input SHA evidence is compared exactly; disagreement yields `mismatched`. All six C2 strings are carried unchanged.

Caller supplies an explicitly trusted C3 ReadOnlyCatalog; no default DjangoCatalog is imported or instantiated. The report retains C3 evidence and exact resolver outcome, including `ambiguous`; no candidate is selected. Public pipeline outcomes include verified/not_found/mismatched/unverified. Unmapped C1 pointers produce structured `needs_mapping` and unverified outcomes. Mapped pointers with no catalog remain unverified. Verification establishes TOC identity only, never question relevance or scholarly approval. Book 622 is reference TOC, not issued-fatwa content.

`ready-for-editor`, `blocked-invalid`, `needs-editor-review` describe intake readiness; `references-unverified` is an additional independent status. A ready-for-editor row can still have no references. Findings and original pointers remain in the report even when no C2 record is created. Every call starts a fresh in-memory batch; no durable queue, authentication, cross-call deduplication, publication or operational permissions are implemented. No media processing, transcription, answer generation, real catalog acceptance or private-case handling.

NOT_DEPLOYED. Gate B NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED.
