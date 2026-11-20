# Selected private exports of actual canonical resources

This opt-in development workflow exports an explicitly chosen, currently
authorized scope from the existing database and private readers. It preserves
the older `editorial_export` fixed-fixture CLI and its exact replay contract.
It does not publish a dataset, deliver a message, alter a scholarly answer or
change any source-rights record during export.

## Working journey

1. An authenticated, currently scoped Mufti opens **التصدير الخاص المختار** for
   the selected case. The chooser searches existing reference editions/index
   entries, linked transcripts, approved knowledge relationships, or case media.
   Reference search requires an explicit edition and search term. Only readable
   resources with the independent export grant become selectable.
2. The user selects one to twenty exact resources, chooses JSON, CSV or JSONL,
   and explicitly chooses whether to request original files. A signed, expiring
   browser-bound form pins the actual candidates, case/evidence versions and
   request key. The service also validates current permissions and source pins;
   possession of the form is not authority.
3. A durable preview job records the exact selected identities and serialized
   record digests. The preview names versions, requested files, unavailable
   slots and a clearly labeled size estimate before ZIP overhead. No source
   dependency is silently added as another exported record.
4. The user confirms the scope and queues it, then runs the bounded preparation
   from the native page. The independent management command can run an already
   queued job without a browser. The job, attempts and result survive leaving
   the page. No fabricated percentage is displayed.
5. The result is `READY`, `PARTIAL`, or `FAILED`. A partial result identifies a
   requested but unavailable file by ordinal; it never claims the whole scope
   succeeded. The ZIP includes only actual included records and files. Retrying
   creates another attempt for the same immutable scope and keeps prior audit
   and artifacts. A changed source requires a new preview.
6. Download requires the same current owner/case scope, explicit download and
   resource grants, source readability, unexpired rights and exact byte replay.
   The artifact itself is never an access capability. Cancellation and expiry
   invalidate platform retrieval while retaining audit. They do not recall a
   copy already downloaded outside the platform.

## Requirement trace

| Owner point | Implemented development behavior | Boundary |
| --- | --- | --- |
| 357 / SPEC-U13-003 | Native explicit multi-resource export from actual canonical readers; durable preview, queue, worker, result and retry | One current case, up to twenty selected resources; no claim to every corpus or an unbounded export |
| 363 / SPEC-U13-003 | Explicit source/version, edition, location, media and relationship metadata schemas | No ORM dump, private review notes or guessed authorship |
| 364 / SPEC-U13-005 | Real JSON, CSV and JSONL serializers with exact Arabic/text/types and documented contracts | XLSX and Parquet are not implemented; listed formats are not represented as implemented formats |
| 365 / SPEC-U13-005 | Deterministic ZIP of chosen data and explicitly requested authorized files, durable task and resumable failed attempt | Bounded development archives; no arbitrary archive upload or unrestricted background service |
| 366 / SPEC-U13-007 | Versioned manifest, bundle identity/time/scope, ordered materials, relationship identities, file paths/sizes and SHA-256 | Integrity is not source authentication or scholarly correctness; manifest does not recursively hash itself |
| 367 / SPEC-U13-010 | Independent scope/resource/sensitive/media grants at preview, preparation and download; full batch/render boundary; no public links | Production rights/role policies remain unapproved and default off |
| 368 / SPEC-U13-010 | Allowlisted transport schema excludes credentials, raw requester capabilities, identity/provider configuration, storage keys/paths and private case originals | Recognizable secret markers in source text/original bytes are rejected; no automatic general personal-data redaction is claimed |

These are implementation boundaries to be assessed with the exact integration
commit and its evidence, not a seven-point acceptance certificate or a new
overall completion percentage. Owner points 354–356 remain import work. Media
examples exercise existing permitted types only; this lane does not count
358–362 as complete or add video, hadith material, full book text or new corpora.

## Authorization and source identity

`FATWA_SELECTED_EXPORTS_ENABLED=False` and
`FATWA_SELECTED_EXPORTS_AUTHORITY=None` are the defaults. Operations additionally
require `FATWA_PRODUCTION=0`, explicit synthetic admission, the owned PostgreSQL
guard and an existing active scoped Mufti identity. No organizer/developer role,
wildcard permission or inferred export grant is introduced.

The configured `ExportAuthority` must implement an atomic, side-effect-free
`projection_epoch()` covering every grant input and expiry. It receives the exact
provider, subject, authorization epoch, case, action and `Resource` when relevant:

| Action | Exact authority required |
| --- | --- |
| `VIEW`, `PREPARE`, `GENERATE`, `DOWNLOAD`, `MANAGE` | Separate operation on the selected current case; `resource=None` |
| `EXPORT_RECORD` | Exact resource identity/version |
| `EXPORT_SENSITIVE` | Additional explicit authorization for transcript, relationship or private-media content |
| `EXPORT_MEDIA` | Additional authorization to include the selected original file bytes |

Only literal `True` permits an action. Sensitive-original permission must be an
explicit decision for that exact resource; public availability and case reading
do not imply it. A knowledge relationship additionally requires export authority
for the underlying source whose metadata/text it carries. Relationships remain
references; they do not silently add another source record to the selected scope.

The existing source-rights ledger is unchanged: READ/CITE/RELATE/PREVIEW_METADATA
still have their existing meanings and EXPORT remains an invalid ledger use.
An export must independently satisfy both current read rights and this new export
authority. Private transcript opening retains the separate KnowledgeAuthority
permission. A source adapter with unversioned external research/knowledge/media
policy cannot authorize a composed export.

Case locks, current identity/provider checks, source-rights ledger snapshots,
canonical case/source bindings, publication/relationship state and grant expiry
guards cover the whole selection, serialization, final response construction and
download. A last callback revoking an earlier resource invalidates the whole
operation. Source withdrawal/permission change rolls back generated artifacts
and nested database changes; a generic failed attempt remains auditable.

## Data contract and files

Every record has exactly these columns/keys:

`ordinal`, `kind`, `identifier`, `version_sha256`, `metadata`, `content`,
`relationships`, `files`.

Reference records preserve exact existing book/edition/index identifiers,
printed location, path, titles and source hashes. They explicitly identify
themselves as index metadata, not full book text. Transcript records preserve
their existing source identity, source/input hashes and exact question/answer
text with time ranges; source answers are not approved case answers. Knowledge
records preserve only the current approved relationship and authorized source
projection, including exact relationship targets. Media metadata omits original
filenames, owner identity, filesystem location and storage backend/key.

- JSON has schema `selected-export-records.v1` and a `records` array.
- JSONL has one complete record per LF-terminated line.
- CSV uses UTF-8, quoted RFC4180 cells and CRLF records. Each data cell is canonical
  JSON, preserving nested relationships, types, diacritics and whitespace. Decode
  it with `csv.DictReader` followed by `json.loads` for each cell. A source string
  beginning with a spreadsheet operator remains a JSON string rather than a
  formula instruction.
- Requested media bytes come only from the existing validated private readers;
  hashes and sizes are verified. Archive paths are generated as
  `media/0001.wav`, never from original filenames or supplied paths. Metadata-only
  export does not require a file that was never requested to exist on disk.
- `manifest.json` uses schema `selected-export-manifest.v1`. It records the bundle
  UUID, creation/expiry times, explicit private scope, chosen format, file option,
  actual requested/included counts, per-ordinal outcomes, source versions and
  relationships. Every other member has a byte count and SHA-256. The response
  supplies the ZIP's own `X-Export-SHA256` and `X-Export-Result`.

ZIP metadata/order/timestamps are deterministic for a job. All members have
fixed generated paths, regular-file permissions and stored compression. No ZIP
extractor or untrusted archive verification capability is added. Downloads have
`private, no-store`, `nosniff`, attachment disposition and current authenticated
POST/CSRF checks. There is no bearer download URL or anonymous dataset.

The schema never reads provider credentials or raw requester tokens. It omits
case questions, answer drafts, staff/private collection notes, authority epochs,
rights evidence and internal configuration unless those are explicitly the
chosen permitted source content represented by the documented resource schema.
Recognizable credential markers in source text or original bytes cause denial;
source content is not silently rewritten. Original media may contain personal
information, so private-original export always needs the distinct sensitive and
media grants and is never reused as a public export.

## Durability, bounds and integrity

`ExportJob` is an immutable owner/case/scope record. `ExportEvent` is immutable
append-only history; the verified event chain determines current state. An
`ExportArtifact` contains the complete private ZIP bytes, manifest, size and hash
for one successful or partial attempt. There is no separate filesystem artifact
to lose during recovery.

Each job has at most twenty resources, ten attempts and 96 events. There are at
most 32 jobs per owner/case; histories are retained. The ZIP is at most 8 MiB;
existing canonical serialization and media size bounds also apply. Ordinary job
expiry is 1,800 seconds, configurable down to one second for synthetic tests;
the generation lease is at most 120 seconds. These are development bounds, not
approved production retention/throughput policies.

QUEUE and START reserve room for completion, cancellation and expiry. New download
events stop at sequence 94, leaving CANCEL at 95 and EXPIRE at 96 available. An
exhausted job remains readable and cancellable/expirable; the UI directs a user
who needs a new download to prepare a new scope. PostgreSQL enforces the same
reserved limits without weakening the 96-event bound.

A worker claim commits before assembly. A crash leaves an auditable RUNNING
attempt and expiring lease. Retry after lease expiry uses a new attempt, and an
old worker cannot complete a later attempt. State changes serialize under the
canonical case lock. Idempotency keys cannot change an action/payload and stale
versions are rejected. PostgreSQL triggers prevent source-scope changes,
artifact tampering, history edits/deletions, invalid lifecycle transitions and
unbound result inserts. Reporting an export never changes canonical case events.

## Integration

1. Install `apps.selected_exports`, apply `0001_initial` and `0002_integrity`, and
   retain disabled/default-deny settings. Use the app-local settings/URL profile
   for isolated development. Its GET staff entry is only a composition adapter;
   the campaign should keep its own staff landing page.
2. Dispatch `views.ACTIONS` to `views.workspace` through the existing authenticated
   `/casework/staff/` endpoint. A native case navigation form posts `exports_open`
   and `case_ref`. There is no new route or guard exception. Existing CSRF,
   loopback, host, request size and rate guards remain active.
3. A field budget of 32 accommodates twenty repeated `selection` fields. The
   app's form validator permits repetition only for that exact bounded chooser.
   Shared source/operation policies must be explicitly configured by the caller.
4. An already queued task can run independently of the page:

   ```sh
   python manage.py run_selected_exports --case-id CASE_UUID --job-id JOB_UUID \
     --subject AUTHORIZED_SUBJECT --synthetic-fixtures-only
   ```

   This uses the existing configured identity directory and export policy. It
   does not accept a credential, grant a role, discover arbitrary files or infer
   permission from operator access. Automatic scheduling is not configured here.
5. Recovery includes tables `selected_exports_exportjob`,
   `selected_exports_exportevent`, `selected_exports_exportartifact`, and the
   three matching `selected_export_*_guard` functions/triggers. No media owner
   registry change is necessary. `recovery_support.populate()` creates a separate
   real synthetic case, reviewed source rights, job, events and artifact and
   returns JSON-safe pins. `verify_restored(pins)` replays the current download,
   verifies the original artifact digest and immutable guard, and proves that
   missing export/identity authority still denies. The integrating lane owns
   the combined encrypted, fresh-process restore drill.

## Verification

Focused labels are `apps.selected_exports.tests` and
`apps.selected_exports.test_durability`. They exercise actual PostgreSQL models,
canonical source readers, real file deletion/restoration, standalone worker,
durable interrupted attempt/retry, current source-rights ledger and expiry,
multiple formats/archive replay, explicit partial failure, native HTTP/CSRF,
exact ownership, mixed-source revocation and final-render denial.

The protected Chromium journey is `apps.selected_exports.browser_tests`. It uses
`chromium_sandbox=True`, native keyboard/form controls, real ZIP download,
current-grant withdrawal, 320/1280 widths, source immutability and blocked external
requests. It is never converted to an unprotected run if the executor cannot
start the protected browser.

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/pg17/bin --major 17 \
  --settings apps.selected_exports.settings -- python manage.py test \
  apps.selected_exports.tests apps.selected_exports.test_durability --noinput
```

Observed run receipts and limitations are recorded in `VALIDATION.md`; integration
acceptance belongs to its exact commit and hosted evidence.

**NOT_DEPLOYED / GATES_HOLD.** No production grant, main merge, public dataset,
external send or source-policy approval is enabled by this implementation.
