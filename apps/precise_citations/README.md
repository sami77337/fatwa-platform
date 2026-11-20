# Precise human citations — synthetic development only

This app adds literal phrase occurrences in a canonical answer, exact library
versions and prior approved answer/part targets, honest descriptive references,
independent human review, correction lineage, and readable print/JSON citations.
The original answer and source versions remain immutable. Saving a citation set
creates a new canonical AnswerRevision and clears previous answer approval.

Candidate owner rows: **543, 550, 553, 556**, directly mapped respectively to
SPEC-U06-001; U06-017; U06-004/018/028; U06-023/026/027. No credit is claimed here
for inherited source cards, unsaved draft handling, PDF/time locators, or row544.
Certification requires the integrated exact-head service, browser and recovery
evidence; this file is not an acceptance receipt.

## Scope and source behavior

The native composer lists explicit occurrences of an entered literal phrase.
Offsets are Unicode code points; no normalization or automatic first-match
selection occurs. The signed, CSRF-browser/actor-bound draft lasts ten minutes.
Every preview, add, reorder, save and reopen revalidates the exact current source.
The browser never holds a reusable source access grant.

Library sources require current separate READ (for originals), CITE and, for
print/export, EXPORT use. Metadata-only editions are descriptive references;
they cannot masquerade as readable digital originals. Text ranges, physical PDF
pages, and recorded-time ranges are checked against the actual pinned original.
The app stores locators and source identities, not private original bytes.

Prior-answer targets require current scope on both cases, an exact immutable
approved revision, and explicit per-resource READ_SOURCE/CITE_SOURCE. An optional
part must belong to that exact answer manifest. Later approved answers are shown
separately to authorized readers without retargeting the citation or asserting
that the historical ruling applies to the new case.

External/non-digital references are manually entered descriptive metadata. An
optional HTTPS link is not fetched or presented as verified content. The reader
states the supplied limitation and opens only the actually documented position.
Changing the intended source or position creates a new answer/citation set and
requires another independent MUFTI review; no technical correction bypass exists.

## Authorization and composition contract

Default flags: `FATWA_PRECISE_CITATIONS_ENABLED=False`,
`FATWA_PRECISE_CITATIONS_AUTHORITY=None`. `CitationAuthority` implements explicit
EDIT/READ/REVIEW/EXPORT and READ_SOURCE/CITE_SOURCE/EXPORT_SOURCE checks using the
current provider, subject, authorization epoch, case and exact resource digest.
Its `projection_epoch` and the identity directory's epoch must be atomic pure
snapshots including scope/active/role/expiry changes. Missing providers deny.
This is development capability plumbing, not acceptance of held role policy.

The outer guard uses the shared graph advisory lock `(546131,1)` and UUID-ordered
case locks before source permission callbacks. It retains current library
boundaries, immutable history/canonical pins, identities, authority object
identity/epoch and actual source bytes until the rendered response completes.
Native commands and their HTML response share one transaction.

Integration hooks are in `integration.py`: wrap the complete canonical use in
`answer_use_boundary`, run `require_for_answer` for exact annotations, and call
`canonical_written` immediately after an intentional canonical decision event.
Prelock `dependency_case_ids` before any caller's case locks. Citation-free and
uninstalled legacy schemas retain their behavior; restored citation rows with a
missing app/flag/authority fail closed. Hooks never project private source content
into requester or public DTOs and never grant publication/delivery.

## Native integration

`editor.workspace` dispatches `precise_open`, `precise_compose`, `precise_review`,
`precise_revision` on `/casework/staff/`. Include `urls.py` under
`/casework/precise-citations/`: sources/UUID/, sources/UUID/file/, print/UUID/,
export/UUID/. All reads authenticate the staff cookie and retain private/no-store,
noindex headers. There are no anonymous citation source routes.

Database inventory: `precise_citations_citationset`,
`precise_citations_citationanchor`, `precise_citations_citationreview`.
These tables own no media files; originals remain with their existing owners.
Append-only SQL triggers validate seals, author/answer/source identity, literal
anchor ranges, correction lineage, exact set counts and independent reviewer.

Tracked evidence labels:

- `apps.precise_citations.tests.CitationTests` — 13 exact-anchor/source/review tests.
- `apps.precise_citations.test_http.CitationHTTPTests` — 6 actual campaign HTTP tests.
- `apps.precise_citations.test_sources.CitationSourceTests` — 11 source, concurrent
  writer, omitted-schema and complete-projection regressions.
- `apps.precise_citations.test_recovery.CitationRecoveryTests` — nonempty three-table
  lineage and fresh authority readers, plus missing authority/current rights denials.

The owned tests executed on real PostgreSQL17.11 and18.7 in focused runs. The
integrated57-test PG18 run also covered29 inherited case/public reader checks;
the PG17 consumer run passed75 tests across affected public collection/knowledge
and publication paths. Later focused checks cover the added PDF, omitted-schema
and cross-case approval regression. Final exact-head certification belongs to the
coordinator's aggregate receipt, not these development runs.

Protected class: `apps.precise_citations.browser_tests.PreciseCitationBrowserTests`.
It uses real CSRF-bound native forms and independent browser identities, literal
second-occurrence selection, preserved unsaved text, exact original bytes, human
review, print/download and native source withdrawal. It records320/1280RTL
screenshots and traces only after success under Chromium sandbox protection, at
`.local/qa/functional-continuation/citations-browser/result.json`.
Hosted execution is pending; no local browser success or sandbox bypass is claimed.

`recovery_support.populate()`/`verify_restored(pins)` expose all three nonempty
tables, SQL functions/triggers, exact corrected history and original-file hash.
The helper persists no authority or credential. The encrypted fresh-process drill
is supplied by the coordinator. All source material and identities are synthetic.
**NOT_DEPLOYED / GATES_HOLD.** No scientific corpus, translation, AI authority,
final taxonomy, live provider or new production role decision is invented.
