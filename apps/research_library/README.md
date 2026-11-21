# Exact source versions, files and separately reviewed uses

This opt-in development module connects a native case-scoped source desk to a
public-looking local reader. It contains fabricated test materials only. It does
not import a scholarly corpus, establish a scholar's attribution, change original
case facts, or satisfy production acceptance. Gate B remains NOT_PASSED, C/D/E
remain HOLD and Phase 01 remains BLOCKED; nothing is deployed.

## Human workflow

The authenticated case workspace links to **مكتبة المصادر والنسخ**. A contributor
enters the source namespace/key, work, exact edition label, creator as stated by
the source, provenance, rights basis, source version and optional recorded text.
They can attach a real book/document, image, audio recording or video. A missing
file produces an honest descriptive reference rather than a false reader.

A subsequent edit appends an immutable edition. It retains the prior original
when no new file was supplied, but receives no previous use approvals. The older
explicitly released edition remains available until its own permission expires
or is revoked. The native desk shows the separate histories.

The creator, reviewer and approver are three different current scoped identities.
Approval selects READ, DOWNLOAD, CITE, EXPORT, OFFLINE, PUBLIC_METADATA and/or
PUBLIC_CONTENT independently. A public release is another explicit, time-limited
step. REVOKE ends public availability; WITHDRAW ends all approved uses of that
edition. Neither deletes the immutable source or its history.

Public material pages at `/library-preview/materials/` display the exact released
edition, a readable citation, and only its permitted text/file. Actual audio/video
players use the verified original bytes. Public downloads and offline copies also
require the releaser's current independent runtime action, in addition to the
edition's reviewed use and live release. Merely opening the staff metadata does
not grant file reading.

## Integrity and current authority

Four immutable tables separate logical source ownership, immutable content blobs,
version history and decisions. A duplicate physical digest does not merge two
source identities or transfer rights. PostgreSQL guards reject updates/deletes,
invalid JSON types/enums, changed seals, broken sequencing and invalid decision
relationships. Application guards pin case/evidence revisions, exact file bytes,
decision history, configured authority, current identities and source heads.

New composed readers require a trusted identity provider's pure `projection_epoch`
capability. It must cover all grant inputs, including expiration/active state.
The whole composition captures it before callbacks and checks it after all final
callbacks; an incomplete/missing capability denies access. It is not a new user
role or a persisted credential. Existing RequestDirectory forwards this trusted
capability for native requests.

Latest-item and source-key readers pin the head including an absent source;
explicit historical reads keep their exact version semantics. Native writes and
rendered responses share one verified owned transaction. A late permission loss
discards the response and rolls back nested changes. Graph-first, sorted case
locking composes public readers with independently released scholarly sources.

Filesystem writers hold sorted digest bindings before the outermost database
transaction until its commit. Import groups explicitly preacquire the same locks.
The library blob is a reference-only GC/recovery owner; it is not admitted to the
older attachment/answer conversion command. Missing owner schemas or an omitted
installed app fail closed. Recovery resolves this table's SHA-256 primary key and
copies its actual external originals into the encrypted fresh-target drill.

## Explicit offline copies and archives

`/library-preview/materials/offline/` is a separate PWA scope, enabled only by
`FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED`. Its manifest, local shell, CSS, icon and
modules are the only automatically cached resources. Private case routes, public
material pages, catalogs and packets have no generic cache handler.
The manifest includes 192px and 512px PNG fallbacks derived from the local SVG,
following the [Chromium manifest guidance](https://web.dev/articles/add-manifest).

An explicit **حفظ هذه المادة على الجهاز** action requests a current independently
allowed OFFLINE packet for one exact released edition. It verifies the response
digest, byte digest, type, size, version path and lease before saving. At most 20
copies are kept. The app displays preparation/expiry times, reads actual local
text/media without a network connection, deletes expired copies and lets the user
remove one or all copies. Online revalidation removes withdrawn or invalid copies.
Loss of connectivity can retain an already authorized, unexpired copy; it cannot
deliver a later revocation to an offline device. The UI states this limitation.

The separate archive form selects up to 20 editions. The server rechecks every
selected OFFLINE grant and source through response construction, then produces a
readable ZIP with escaped Arabic HTML, local assets, source/version references,
preparation/permission timestamps and a SHA-256 manifest. No case identifiers,
credentials, private provenance notes, actors or approval records are exported.
One unavailable selected item cancels the complete package. A downloaded archive
is a retained copy and cannot receive later revocations automatically.

## Bounds and evidence

This development implementation supports at most 64 items per case, 64 versions
per item, 64 simultaneously leased public candidates, 8 cards per page and 192000
bytes per original. A video must decode fully in a bounded local worker: supported
MP4/WebM codecs, at most 60 seconds and 1280×720, no remote URLs/playlists or file
protocol access. Books/documents, images and audio reuse the established private
media validators. The specialized hadith library remains deferred by D-072.

Service/native proof families are `tests`, `test_http`, `test_storage`,
`test_offline` and `test_recovery` in this app. Actual file-system GC preservation,
invalid sealed SQL rows, latest/historical race distinction, late revocation,
independent grants, true decoded audio/video, ZIP contents and current route
boundaries are exercised. `static/research_library/offline/core.test.mjs` verifies
client integrity and expiration rules with Node's test runner.

Protected browser journeys and the encrypted fresh-process recovery drill are
required by the continuation receipt on the exact tested commit. A local service
test success alone is not counted as a completed owner requirement. The original
556-point inventory and prior 57 completed points are kept separate in
`docs/product/functional_continuation/scope_plan.json`.
