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
- Classified reads require a recorded exact-target classification and a separate
  current `PrivacyAuthority` grant. Missing classification may permit only the
  separately authorized private human work described below. Unknown, missing,
  malformed or expired policy data deny access before constructing content or counts.
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
current-identity pins in every enclosing privacy projection. `require()` checks the
current permission and identity before consuming each source. Closing a projection
compares pure complete policy/identity epochs, source/label pins and the earliest
deadline after the last domain callback. It does not invoke a new provider after
that domain's final source checks. An adapter can explicitly run `callbacks()`
before all final pins when its existing boundary requires a second callback pass.
A late revocation or reclassification discards the whole response.

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
The same checkpoint passed **11/11 on PostgreSQL 18.7 (4.706 seconds)**.

Second checkpoint adds private case/read-list/requester boundaries, actual answer
and attachment DTO/byte gates, requester answer availability/counts, and source
provenance checks for copied attachment/transcript evidence. The actual requester
portal and signed GET/HEAD/Range tests prove that staff privacy grants cannot be
borrowed by a requester, a PUBLIC case cannot expose an unclassified child, and
late domain-to-privacy or privacy-to-identity revocation discards output. The
selected group passed **38/38 on PG17.11 (43.944 seconds)**:

```text
apps.data_privacy.test_ledger
apps.data_privacy.test_private_hooks
apps.private_media.test_signed_links
tests.casework.test_editor_profile_compatibility
```

The native classification editor and remaining library/search/export/public/
operational hooks are still pending at this second checkpoint. The middleware
hook is prepared, but coordinator-owned campaign settings have not enabled it.

The production role/data-type matrix, real object classifications, legal retention
durations, actual providers and operational key custody are missing owner inputs.
This implementation does not invent them. It also does not claim SOFT_DELETE,
anonymization, PURGE or removal of already downloaded external copies.

**NOT_DEPLOYED; GATES_HOLD.**

## Current integration checkpoint (2026-11-21)

The campaign now installs the ledger and the response projection middleware, while
leaving the feature off and its authority unset by default. The finite target
catalog additionally includes KNOWLEDGE_REVISION and SERIES_VERSION. Native
classification exists at `/casework/staff/privacy/` and
`/casework/operations/privacy/`, using the real current session/role and separate
VIEW_CLASSIFICATION/CLASSIFY grants. Classification history is available without
permission to read original contents; each native form binds its target, source,
previous revision, operation and CSRF token.

Private original readers, source intake, library/search/export, operational
queues, precise/timed/PDF sources, public derivatives and scholarly relations now
consume exact current labels. Public source readers retain the actual publisher
separately from the scholarly actor a nested source service uses. PUBLISH for a
public-copy dependency cannot be borrowed by a private READ. Public print/text
copy endpoints require an independent public EXPORT grant. Reader reference and
link metadata still require their own current native grants. Both legacy and
composite signed-return adapters recheck the exact ANSWER before composing a
plan or resolving a reserved part; a case envelope alone cannot authorize it.
Late revocation withholds the result and rolls back a newly staged plan.

AI candidate retrieval, quality reports, team inbox rows and identity joins also
apply the current classification boundary before restricted data or counts are
returned. The enabled feature never invents a classification for a newly created
answer or derivative. Human classification remains independent of authoring.

The real protected two-role, four-level native journey passed on PostgreSQL 17
and 18 at source `ad92317507375aaabfb7b22aabb958495ab8614b` in run
`44904565838`. That run's AI journey failed at its final textarea comparison and
is not a whole-suite PASS. The diagnostic timeout disappeared; the browser's
native CRLF submission is now checked against the exact submitted text instead
of an LF-only Python fixture. No original text is normalized by the product.

The aggregate registry requires this native journey plus every privacy service
family, and a fresh encrypted restore of the one nonempty classification table.
The restore helper keeps four dated labels and exact original/source/event bytes,
proves SQL update/delete rejection, runs thirteen named current-use denial checks,
and repeats positive reads after restoring fresh explicit grants. Restored labels
provide neither current identity nor runtime permission. Focused and historical
native results are recorded separately; final exact-head certification remains
pending. Publication-destination and schedule consumption now require independent
exact-source PUBLISH, and public library/knowledge/collection/teaching discovery
requires SEARCH before filtering, facets, counts and sitemap links. Direct detail
READ remains independent. The next aggregate must prove these additions together.

## Explicit private work while classification is pending

SPEC-U14-001 prohibits making completed classification or transcription a
prerequisite for a human answer. An unclassified private CASE or exact child can
therefore use a separately typed `UnclassifiedWorkGrant`, issued by the current
configured authority for STAFF READ only. The grant binds the exact source digest,
case, actual principal/role/auth epoch, independent purpose and a finite deadline.
The default authority denies it. Missing production policies remain unset.

This is an absence-of-classification pin, not a fifth human sensitivity level.
It creates no `ClassificationRevision`; any existing classification, malformed
history or stale source prevents fallback. Changes to the source, classification,
identity, policy or deadline after rendering withhold the response. SEARCH,
EXPORT, PUBLISH, AI, public/requester access and classification management never
inherit this grant. The native staff inbox can list explicit private work, while
every nonempty queue search first requires separate CASE/original SEARCH and
excludes readable answers or copied evidence lacking exact child SEARCH grants.

The native browser journey drafts and approves through the real MUFTI forms,
compares the persisted answer to the actual native POST bytes, leaves the original
question/evidence and classification ledger unchanged, and reuses the rendered
form after current work permission is revoked. Its protected hosted execution is
required alongside the existing two-role classification journey. The encrypted
restore creates only a fresh synthetic work authority for a positive check; it
preserves all thirteen independent denial checks and never restores a runtime grant.
