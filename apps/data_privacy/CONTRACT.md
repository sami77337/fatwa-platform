# Data sensitivity — owner rows 391–395

Base: `231adcd63fb6fd2ace3949f94c775b9c9f337701`, recovered development PR 244.
This is an opt-in development implementation. No production grant provider,
classification, migration execution, or owner policy is selected by its defaults.

## Source and exact meaning

The retained owner matrix maps 391 to PUBLIC, 392 to INTERNAL, 393 to CONFIDENTIAL,
394 to RESTRICTED, and 395 to their effects on permissions, export and search.
`SPEC-U14-016` separates sensitivity from scientific approval, release, publication
and export. A PUBLIC parent cannot expose all children. `SPEC-U14-017` includes
text, audio, image, filenames, transcripts, snippets, result counts, links, graphs,
reports, notifications and previews, filtered before composition. D-043 separates
classification from CLOSED/ARCHIVED/SOFT_DELETE/PURGE and leaves retention periods
for a later owner policy.

## Explicit contract

- `FATWA_DATA_PRIVACY_ENABLED=False` and `FATWA_DATA_PRIVACY_AUTHORITY=None`.
- Enabled reads require a recorded exact-target classification and a separate
  current `PrivacyAuthority` grant. Unknown, missing, malformed or expired policy
  data deny access before constructing content or counts.
- READ, SEARCH, EXPORT, PUBLISH and AI are independent actions. A READ grant does
  not satisfy another use. CLASSIFY and VIEW_CLASSIFICATION are management actions,
  independent of reading the classified contents.
- PUBLIC is necessary for an anonymous public projection and does not itself
  grant it. Existing scientific approval, explicit public-copy release, current
  publisher/source permission, private case scope and download gates still apply.
- Staff keep their actual current MUFTI/ORGANIZER_ADMIN/ORGANIZER identity. No
  synthetic elevated principal is substituted for an operational user. Requester
  uses bind their actual current case capability and expiry. Public copies use an
  explicitly public principal; their private originals remain private.
- Each classification is a human append with source pins, previous digest,
  sequence, actor/provider/auth epoch, policy digest, reason and database timestamp.
  It neither rewrites source data nor appends canonical case events. Database
  triggers reject history update/delete, skipped sequences and altered seals.
- A case label covers its private case envelope. Exact answer, attachment,
  library, transcript and released derivative identities are independently
  classifiable; none receives a PUBLIC label by inheritance. A changed source
  identity/digest or newly bound source receipt requires explicit new classification.
- Disabling the feature or using an older profile cannot silently bypass an
  existing recorded label. The old profile performs a narrow table-existence/read
  check without importing an uninstalled model. Unclassified legacy records keep
  their existing behavior while the feature is off.

`catalog.TARGETS` is a closed model/path inventory, not a caller-provided content
type. It covers CASE, ANSWER, ATTACHMENT, ANSWER_PART, LIBRARY_VERSION,
SOURCE_VERSION, SOURCE_RECEIPT, TRANSCRIPT_LINK, RECORDING_TRANSCRIPT, PUBLICATION,
PUBLIC_MEDIA, PUBLIC_KNOWLEDGE, PUBLIC_COLLECTION, PUBLIC_TEACHING and LESSON_VERSION.
The authority receives bounded identity/source pins and the exact label/operation,
not question text, media bytes, a requester token or an automatically inferred grant.

## Projection and concurrency

The source domain authenticates and authorizes its own operation independently.
The privacy check is an additional veto before its DTO, filename, link, count or
bytes are composed. Each use retains its policy, exact source, classification and
current-identity pins in every enclosing privacy projection. Closing a projection
rechecks permission callbacks and current identity first, then compares all pure
pins and the earliest deadline after the last callback. A late revocation or
reclassification discards the whole response.

Readers and classification writes share a target advisory transaction lock.
Classification writes obtain the existing scholarly graph lock before the canonical
case lock, then the target lock. They do not replace any existing source lock.
Retries carry a unique request key plus exact previous/source digest. An old or
cross-source form cannot append to a changed classification history.

## Integration inventory for row 395

The first checkpoint contains the ledger and denial tests only. Until the hooks
and native flows below have passed, rows 391–395 must **not** be marked complete.

| Surface | Existing enforcement point | Required privacy placement |
| --- | --- | --- |
| Private case and requester envelope | `casework.services._staff_case`, `_token_case`; `casework.delivery` delegates | Before any case DTO and throughout outer answer-use callbacks |
| Answer text/parts and question attachments | `answer_media.services`, `case_attachments.services` | Exact child target, before text, filename, part list and original bytes |
| Operational queue/detail/notes/transcription | `operational_workspace.boundary.Guard._permission` and `scope` | READ_CASE before sections/counts; exact resource checks and final adapters/pure pins with real role |
| Bound/unbound source intake and raw originals | `source_case_intake.desk_services.inbox/detail/timeline`; raw service | Receipt check before source filters/pagination/counts; case check remains independent |
| Staff material versions and blobs | `research_library.services.Boundary`, read/authorize/file/browse | Exact version before metadata or bytes; explicit SEARCH/EXPORT uses |
| Current canonical search generations | `canonical_search.policy.Scope._permit/read`; `sources` and `recordings` | Filter authorized case and exact child before query/result count, snippets and index status |
| Research workspace and imported transcripts | `research_workspace.services.search/open_resource`; current source-rights adapters | Exact source and SEARCH before rows/counts; READ on later open |
| Selected export jobs/previews/downloads | `selected_exports.policy.boundary` and `resources.read` | EXPORT before selected-source content/artifact reads, rechecked on every job/download |
| Private citations/media locators | Existing answer-use, library, timed/PDF/precise and signed-link byte readers | Consume the same exact source/privacy boundary on every use, including HEAD/Range |
| Publication preparation and destination/schedule plans | `experimental_publication.services` plus exact source publication boundary | PUBLISH on the private source and independently classified edition; no automatic release |
| Public fatwa list/detail/references | `library_preview.services._current/_projection/browse` | Public edition and consumed sources before DTOs, facets and counts |
| Public library/API/offline/download | `research_library.public.public_projection` and `Snapshot.authorize_use` | Public version before records map, file metadata and exact bytes; explicit use stays independent |
| Public knowledge, collection and teaching graph | `public_knowledge.public.projection`, `public_collections.services.public_projection`, `public_teaching.services.public_projection` | Exact released derivative before graph link, label, item count or nested source |
| Public recordings and selected transcript segments | `public_answer_media.public.publication_projection/recording_projection` | Exact public-media copy and transcript checks before optional media counts or bytes |
| Reader copy/print/offline tools | `public_reader_tools.services.reader_projection` | Current public-copy boundary plus explicit export-like use; saved browser copy grants nothing |
| Relations/lesson graphs/related answers | `scholarly_links` and `knowledge_links` projection boundaries | Both admitted endpoints and exact derivative before links, snippets and counts |
| Reports, inbox notifications and identity links | `data_quality.projection`, `team_updates.read_inbox`, `identity_registry.boundary` | Current case/target admission before report text, row counts or joined identity labels |
| Citation-candidate AI | `ai_gateway.services.authorized` and exact source readers | Explicit AI in addition to READ/CITE; never classify or change canonical text automatically |

## Evidence and remaining work

`test_ledger` uses real owned PostgreSQL. It checks append-only history, the four
levels, independent action grants, unknown-source denial, current identity/policy
changes, recorded-label enforcement under disabled/older profiles, stale forms,
and canonical-source preservation. Integration tests, native classification flows,
protected browser evidence and restored-source verification are separate next
steps. A schema or green unit suite alone cannot establish the table above.

First checkpoint: **11/11 PASS on PostgreSQL 17.11 (5.080 seconds)**, using
`apps.data_privacy.settings` and the owned-cluster runner with real migrations.

The production role/data-type matrix, real object classifications, legal retention
durations, actual providers and operational key custody are missing owner inputs.
This implementation does not invent them. It also does not claim SOFT_DELETE,
anonymization, PURGE or removal of already downloaded external copies.

**NOT_DEPLOYED; GATES_HOLD.**
