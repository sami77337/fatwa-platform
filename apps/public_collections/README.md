# Human-curated public collections and topic pages

This development-only app adds durable, reviewed collections over **already explicitly released exact versions**. A curator can build a topic from material belonging to several authorized cases, select the order, add a separate public title/introduction, and submit an immutable revision for independent review. The original questions, answers, recordings, transcripts and library bytes remain in their original stores.

**NOT_DEPLOYED / GATES_HOLD.** The app is disabled by default. Synthetic runtime authorization does not accept a final taxonomy, corpus, production publication policy or the held U03/U10 policies. There is no AI authoring, automatic scientific inference or external service call.

## Completed workflows

The native current-case workspace supports:

- Creating `TOPIC`, `COLLECTION` and `HOME` pages, selecting exact currently released materials, and saving an immutable draft.
- Cross-case membership only when the current curator has current scope and exact `READ_MEMBER` authority for every selected material's owning case. An opaque source identifier is not an access grant.
- Editing the title, introduction, membership, featured selection and order by creating another revision. A new draft stops the old revision from being the currently released collection; it never silently inherits an old review or lease.
- Native up/down controls and removing checked members. The previous order and exact pins remain in history.
- A separate `REVIEW` actor, then an `APPROVE` actor distinct from both the author and reviewer. Approval does not release a page.
- An explicit `RELEASE` of the exact approved revision for 5, 15, 30 or 60 minutes, shortened to current source/identity deadlines. `REVOKE` names one exact release and cannot resurrect an older lease. `WITHDRAW` preserves the full history.
- Reading current and historical revisions under current rights. If a source has become unavailable, the staff view redacts its title, introduction, member list and internal notes while retaining the decision history and withdrawal operation.
- Exact released parent topics up to the bounded depth; cycles are rejected. A changed or unavailable exact parent prevents a child from remaining public.

The anonymous portal lists released collections and topics, offers a query, page-kind and topic filter, shows curated featured topics and HOME memberships grouped as fatwas, scholars, lessons and library materials, and links to the existing readers. The question-entry link is displayed only when the existing casework entry capability is enabled. An empty collection index and an empty topic have explicit empty states.

### Withdrawal policy

A public collection is a complete reviewed composition. **If any selected exact member or exact parent is unavailable, the entire collection is omitted from the public index and its direct page returns an unavailable response.** The implementation does not expose the number, names or positions of withheld members, and does not leave an introduction attached to a silently shortened selection. This is deliberately visible in the native editor so the curator can prepare and review a replacement revision.

The public templates receive only safe DTOs: separate public page ID, kind, title/introduction, version, public parent link and safe material cards. They receive no private case IDs, actor IDs, source hashes, private original text, review notes or internal member pins.

## Sources and exact-version boundaries

Supported member kinds are:

| Member | Exact stored pin | Reader and independent release requirement |
| --- | --- | --- |
| `PUBLICATION` | `PublicationEdition` ID, content SHA-256, number and owner case | Existing `PreviewPolicy.PublicationGrant` and current `public_knowledge.public.projection()` |
| `PRESENTATION` | Released `PublicRevision`, hash, number and owner case | PublicKnowledge's reviewed language presentation and explicit current release |
| `SCHOLAR` | Released `PublicRevision`, hash, number and owner case | Separately reviewed sanitized public profile and its current release |
| `LESSON` | Released `PublicRevision`, hash, number and owner case | Separately released public lesson metadata plus current scholarly link/source/policy checks |
| `LIBRARY` | Released `LibraryVersion`, digest, number and owner case | ResearchLibrary's independent use approval, explicit release and current exact-version projection |

A collection stores only the pin and its own editorial text. It does not copy member text or bytes. A descriptive library reference is presented as metadata; a collection does not grant `PUBLIC_CONTENT`, `DOWNLOAD`, `OFFLINE`, `EXPORT` or private-media access. Opening a material link invokes the original reader again.

A public lesson card may be owned by case A while its underlying recording belongs to case B. Curating the already sanitized public card requires the curator's exact member authority on A. It does **not** imply access to B's private recording. PublicKnowledge independently revalidates its recorded release actor on the necessary owner/source cases and the scholarly `READ_LINK` / `READ_LESSON` authorities. Both source cases are included in the outer lock closure and final source pins. No recording bytes are delivered by the collection.

### Complete response composition

`sources.boundary()` takes the graph advisory lock first, computes the fixed-point closure of collection owners, current publication grants, current library releases and scholarly source/target cases **without permission callbacks**, and then locks every case in UUID order. It enters the existing PublicKnowledge and ResearchLibrary projections within that same verified synthetic queue transaction.

The outer boundary captures canonical rows, public histories, source configurations, authority object identities and atomic policy epochs before reader callbacks. It retains both readers through actual HTML rendering. After nested readers exit it runs the remaining scholarly callbacks, verifies source bytes without permission callbacks, and compares pure source/history/configuration fingerprints and original deadlines. A callback from a later reader cannot silently invalidate a source already checked by an earlier reader.

`services.scope()` also captures the configured identity provider and its atomic directory generation **before** any source callbacks. After all nested exits it rechecks that generation, collection policy identity/generation, identity deadlines and, for read responses, the complete collection history. This catches a source callback revoking a different collection release actor after the collection's earlier identity checks. Missing snapshot support denies this new composed feature.

Native mutation dispatch and the response read/render are enclosed in one outer `synthetic_queue_atomic()`. A final render failure or authority revocation rolls back the submitted mutation. Exception-to-HTTP mapping occurs outside that transaction. An arbitrary caller transaction cannot replace the owned synthetic-database guard.

## Authority and integration contract

Register `apps.public_collections` and its migrations in the development composition. The dedicated app settings module extends `config.settings.campaign_review` for isolated verification.

Default settings:

```python
FATWA_PUBLIC_COLLECTIONS_ENABLED = False
FATWA_PUBLIC_COLLECTIONS_AUTHORITY = None
```

The configured authority must be an instance of `CollectionAuthority`. Its `permits(...)` returns literal `True` for the exact current provider, subject, auth epoch, case, operation, kind and resource identity/hash. Operations are `EDIT`, `READ`, `READ_MEMBER`, `REVIEW`, `APPROVE`, `RELEASE` and `WITHDRAW`. Staff role, a source's public visibility and prior human review do not create these permissions.

`CollectionAuthority.projection_epoch()` must return a nonempty string of at most 2,000 characters. It is an **atomic, side-effect-free generation of the complete relevant current policy including expiry**, not another permission callback or a constant capability token.

The trusted configured identity provider must likewise implement `projection_epoch()` with the same type/bounds. Its generation must cover every subject's existence, active state, role, case scope, authorization epoch and identity expiry source. The native `RequestDirectory` forwards this snapshot with its authenticated binding. This requirement applies to the new composed reader; it does not add a grant to legacy readers. Fixture providers explicitly implement a synthetic snapshot; no authority or identity credential is stored in collection tables or recovery pins.

Existing PublicKnowledge and preview configuration remain prerequisites. ResearchLibrary members are available only when both `FATWA_RESEARCH_LIBRARY_ENABLED` and `FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED` are true. The collection feature never changes those source flags or releases materials itself.

Shared integration hooks:

- Dispatch `editor.ACTIONS` (`pc_open`, `pc_revision`, `pc_save`, `pc_reorder`, `pc_act`) to `apps.public_collections.editor.workspace` from the existing authenticated staff route.
- Add a current-case navigation form with `action=pc_open` and the actual `case_ref` when the collection feature is enabled.
- Mount `apps.public_collections.routes` at `/library-preview/collections/`, namespace `public_collections`.
- Keep the existing public catalog, PublicKnowledge and ResearchLibrary routes intact. The collection prefix does not shadow them.
- The focused HTTP fixtures, dedicated settings and protected browser journey use **`config.campaign_urls`**, the real shared dispatcher and current-case navigation. The historical isolated wrapper is not used by the final proof.

Public routes are the index, `items/<public_id>/`, and `collections.css`. They use the shared preview `safe_read` guard, no-store/noindex headers, strict CSP and local synthetic-runtime restrictions. Staff forms use the existing authenticated session and CSRF protections; no new authentication mechanism is introduced.

## Integrity, concurrency and bounds

There are three append-only tables:

| Model | Table | Preserved data |
| --- | --- | --- |
| `CollectionSeries` | `public_collections_collectionseries` | Separate private/public IDs, kind, owning case |
| `CollectionRevision` | `public_collections_collectionrevision` | Ordered exact pins, editorial text, exact parent, author, request ID, case/evidence versions and content hash |
| `CollectionAction` | `public_collections_collectionaction` | Ordered human decisions, exact revision/hash, actor epoch, release deadline and exact revocation target |

SQL guards reject updates/deletes, forged source identities, mismatched source versions/cases, malformed JSON, duplicate or invalid transitions, non-independent approval, parent cycles, invalid public/private IDs and overlong leases. Protected foreign keys preserve history. Source pin validation covers both existing publication/PublicKnowledge tables and the optional installed library tables.

Optimistic checks bind each write to current case/evidence and content/action versions. Idempotent request IDs accept an exact replay and reject changed inputs. The real concurrent-write regression runs two database connections and proves one new revision wins while the other receives a conflict.

Explicit limits are 16 members per revision, 32 series per owner case, 128 revisions per series, 256 actions per revision, a topic depth of 5, a composed case closure of 192, 256 visible/current collection candidates, 4,096 retained revisions in the public projection and 256 staff source choices. Exceeding a boundary fails closed; it does not silently truncate a reviewed page.

## Verification and recovery

Focused test labels:

```text
apps.public_collections.tests
apps.public_collections.test_scholarly
apps.public_collections.test_recovery
```

They exercise native CSRF forms and independent actors; actual two-case publications; exact released scholar, presentation and lesson metadata; library metadata/content boundaries; immutable source preservation; SQL guards; optimistic concurrency/replay; lease expiry/revocation; missing scope and exact grants; withdrawal during HTML rendering; late policy and distinct-actor identity revocation; source byte checks after other reader callbacks; parent dependencies; and native mutation/response rollback.

The complete focused set passed **28/28** on fresh owned PostgreSQL **17.11** and **18.7** clusters on 2026-11-20 (32.032 s and 32.385 s respectively). Ruff passed and the model/migration drift check reported no changes. The dependency snapshot was the library core, lifecycle core and shared native/identity integration through `1940da6`. Protected browser and encrypted restoration evidence are tracked separately; those are not implied by these service/HTTP results.

Protected browser label:

```text
apps.public_collections.browser_tests.PublicCollectionsBrowserTests
```

This journey requires the integrated `config.campaign_urls`, sandboxed Chromium, the existing staff session setup and actual native forms. It performs cross-case selection, reordering, separate review/approval/release, anonymous navigation/filtering and explicit revocation. It checks RTL and overflow at 320 and 1280 pixels and records screenshots and a trace. Its proof directory is `.local/qa/functional-continuation/collections-browser/`. Local Chromium sandbox failure is not a pass and must not be bypassed. Hosted protected execution supplies the final browser evidence.

`recovery_support.populate()` creates a separate synthetic case, a released descriptive library version and a reviewed/released topic, leaving all three collection tables nonempty. It returns exact row/source/version pins with no credentials or persisted authority. `verify_restored(pins)` supplies fresh explicit fixture authorities, verifies the original release deadline, exact library member and private source hash, and reads the restored public topic; it also proves storage alone cannot authorize publication. `TABLES`, `FUNCTIONS` and `TRIGGERS` expose the recovery inventory. The coordinator's encrypted fresh-process recovery drill is the full restoration evidence; the app-local test verifies the helper contract.

## Requirement accounting and limits

The strongest newly delivered owner-point candidates are **283** (a meaningful cross-case topic hub, `SPEC-U09-015`) and **291** (curated scientific collections, `SPEC-U09-019`). Final closure depends on the exact integrated tests/browser/recovery evidence.

Row **284** supplies examples and is not a separate implementation unit. Row **285** is not claimed: this app does not fabricate an absent hadith corpus or implement every knowledge type. Existing baseline PublicKnowledge already listed topics, fatwas, scholars and lessons; the new HOME selection and order are real workflows, but merely displaying those existing card types again is not automatic new credit for rows 260–264. The coordinator must compare the original wording and existing baseline before assigning any such credit.

There is no claim of production readiness, public internet publication, accepted global taxonomy, final role policy, rich scientific ranking, semantic search, audio playback, downloading/offline rights, or new source ingestion by this app. Those remain with their explicitly authorized source modules and gates.
