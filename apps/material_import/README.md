# Durable material import center

This development workflow stages explicitly synthetic material batches, previews
their actual effect, requires an independent human import decision, and writes
usable immutable versions through `research_library.services.write_material`.
It does not create cases, answers, scholarly approvals, publication releases,
accounts or source-use grants. Original bytes, mappings, plans, decisions,
application receipts and events remain available after processing.

**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.** No real corpus, historical
approval authority, organizer permission or production migration is inferred.

## Connected native workflow

1. Open an authorized case in the existing Mufti workspace and choose the material
   import center. Upload JSON, CSV, JSONL or a manifested ZIP, name the source
   namespace, describe provenance and the available basis for use, and explicitly
   acknowledge synthetic data. Renaming identical input does not create a second
   batch. Conflicting provenance for the same receipt is refused.
2. Choose source columns for the declared material fields. Original column names
   are arbitrary; target fields are an allowlist. Save the mapping, then create
   a durable dry run. No library material is written by either action.
3. Inspect additions, exact duplicates, missing files, invalid material fields,
   unreferenced ZIP members and conflicts with existing human work. Missing optional
   transcript text is not a defect. A changed existing record is blocked until an
   explicit choice preserves it or proposes a new version. Empty optional cells
   preserve existing values; omitted files preserve the old file. Deletion is not
   an import operation. A material's type cannot be silently changed.
4. Another currently authorized Mufti opens the batch, reviews the exact plan and
   records a decision plus a provenance-verification note. The batch author, latest
   mapping author and plan author cannot approve their own work. This is technical
   approval to apply a particular plan, not verification of a religious ruling.
5. Execute the approved dependency groups. Each group writes its canonical library
   versions and application receipt in one transaction. An error rolls back the
   whole group. Earlier committed groups remain explicitly partial; retry only
   applies outstanding groups. Results link to the actual native library reader.
6. Cancellation stops the remainder without deleting original input or already
   applied materials. Expiry blocks further execution while retaining the audit.
   Changed case evidence, mappings, target versions or permissions invalidate the
   relevant plan instead of overwriting newer work.

## Supported source contract

Limits: **20 rows**, **192000 input bytes**, 24 source columns, 32 batches per case,
32 mapping revisions and 32 plans per batch. Default execution lifetime is
1800 seconds, configurable only within 60–3600 seconds. There are at most 128 journal
events; capacity checks retain cancellation space. Reading and expiry do not
consume journal capacity. The existing HTTP request limit and 32-field form limit
are retained.

Every row has `_synthetic: true` in JSON/JSONL, or `_synthetic=true` in CSV.
Other cells are strings. Original Unicode, whitespace and embedded CR/LF remain
unchanged. JSON duplicate keys, nested values, numeric identifiers, invalid UTF-8,
privileged/credential-like column names and unsupported formats are refused.

The mapping targets are:

| Target | Meaning |
| --- | --- |
| `external_id` | Explicit source-local identity; never a local database primary key |
| `kind` | BOOK, DOCUMENT, IMAGE, AUDIO or VIDEO |
| `title`, `work_title`, `source_version` | Required material and source-version descriptions |
| `edition_label`, `creator`, `description`, `source_locator` | Optional source metadata |
| `provenance`, `rights_basis` | Source assertions; omitted mappings use the batch description, never grant permission |
| `language` | `ar` or `en`; new material defaults to `ar` |
| `recorded_text` | Text actually supplied; no OCR, transcription or corpus reconstruction |
| `file_member` | Exact manifested ZIP file member; empty means no newly supplied file |
| `group` | Explicit bounded atomic group; defaults to the external identity |

Namespaces and external identities use `[A-Za-z0-9][A-Za-z0-9._:-]{0,99}`. Different
namespaces do not match automatically. Similar titles or physical file hashes do
not merge logical material owners.

A ZIP contains exactly `manifest.json`, one of `records.json`, `records.csv` or
`records.jsonl`, and its declared `files/<safe-name>` members. Only ZIP_STORED is
accepted. The parser performs no extraction; it rejects duplicate members,
compression, encryption, symlinks, traversal, hidden extras and mismatched file
sizes/hashes. The manifest schema is:

```json
{
  "schema": "fatwa.material-import.v1",
  "synthetic": true,
  "records": "records.json",
  "files": [
    {"path": "files/source.txt", "filename": "source.txt", "media_type": "text/plain", "sha256": "<actual SHA-256>", "size": 123}
  ]
}
```

File admission uses the canonical library's pure validator, including its actual
isolated video decoder. Invalid files block the dry run before approval. Hashes
prove internal byte consistency, not external authenticity or a license. An
unverified historical `approved` field is never promoted to an approval; such
privileged columns are outside this configured source contract.

## Exact authorization and concurrency boundaries

Configure `FATWA_MATERIAL_IMPORT_ENABLED=False` and
`FATWA_MATERIAL_IMPORT_AUTHORITY=None` by default. `ImportAuthority` separately
authorizes VIEW, STAGE, MAP, PLAN, REVIEW, APPLY, CANCEL and EXPORT for the current
provider, subject, auth epoch, case and namespace. Canonical library VIEW/EDIT
checks remain mandatory. No caller-supplied role or grant is accepted.

Both authority and identity providers must expose an atomic, side-effect-free
`projection_epoch()` contract. A grant, subject, scope, activity, epoch or expiry
change must change its revision. Missing/unavailable snapshots fail closed.
The authority object itself is pinned by identity, so equal revision strings or
a custom value-equality method cannot authorize a replacement provider.
Browser requests use the existing RequestDirectory and CSRF/session binding.
Signed form state also pins case/evidence revisions, batch journal sequence,
source targets, plan and a request nonce; it carries no raw source file or text.

The importer holds an outer guarded transaction around each group and around
composed pages. The library's final callbacks finish before the importer compares
the final pure authority/identity snapshots and material heads. For a write group,
expected heads advance only for its declared canonical results. An authority
callback cannot insert an unselected extra item and make it an accepted side effect.
Readonly previews also pin absence, so a late new target invalidates an ADD plan.
Native import pages additionally pin all six immutable import histories, including
an initially empty inbox and expiry transitions. A callback that cancels, remaps
or inserts a batch cannot return the earlier page with stale controls. A single
native staging/mapping/plan/decision/cancellation command commits with its rendered
response; final render denial rolls it back. Apply retains its documented atomic
groups and durable partial results instead of wrapping the whole batch in one transaction.

File-bearing groups complete an authorized readonly preflight, acquire the exact
content-hash storage locks outside the database transaction, then revalidate the
approved plan inside the group transaction. The locks remain held until canonical
file references and the group receipt commit. Filesystem garbage collection uses
the canonical library reference registry; the importer creates no duplicate blob owner.

Every plan binds exact input and mapping digests, current target item/version/
number/digest, current case/evidence and expiry. A raw replay, concurrent request
or request retry cannot create duplicate canonical versions. New versions preserve
old rows; source use permissions are reviewed independently for the new version.

## Authorized round-trip packages

The separate native chooser previews only explicitly checked current materials
from one namespace. Its library listing has eight rows per page; the service
accepts at most 20 selected rows. Actual preview/download requires **both** import
EXPORT permission and the library's exact current runtime EXPORT permission plus
its independently reviewed EXPORT use for every selected version. VIEW, READ,
import approval and previous publication do not imply that grant.

The deterministic ZIP contains canonical payload text, exact external keys,
selected original file bytes, size/hash relationships and an `origin` manifest.
That origin carries the source namespace and old local item/version identifiers,
version number/digest and record digest. These are provenance only. Reimport must
retain the declared namespace and canonical round-trip mapping; the new case
generates its own local item/version IDs. It receives no approval, publication,
identity, access token or source-use permission. A same-case replay skips exact
current material instead of duplicating it.

The entire final ZIP must fit the same 192000-byte limit. Oversize fails rather
than silently omitting members. Missing originals and permission withdrawal close
preview/download. A recorded preview pins the exact bytes; the download is checked
again through response construction. `RoundtripReceipt` records selection,
manifest, principal, size and artifact hash without copying source decisions or
credentials. Same-request replay regenerates identical bytes only while all
current rights still permit it.

This is a declared product-data transfer test, not backup recovery, a generic
archive migration, an offline application or a public dataset.

## Registration and recovery

Integrator-owned configuration installs `apps.material_import`, applies its five
migrations and keeps the defaults above closed. `apps.material_import.settings`
is an optional local composition. The actual HTTP/browser tests use
`config.campaign_urls` and the real `/casework/staff/` dispatcher.

Dispatch `views.ACTIONS` to `views.workspace`, add the `mi_open` same-case tab, and
retain the current guards. Upload alone accepts bounded multipart `source_file`;
other forms are strict URL-encoded CSRF requests. `mi_example` returns a fabricated
CSV through an authenticated POST. Round-trip actions are `mi_export_open`,
`mi_export_search`, `mi_export_preview` and `mi_export`.

There are seven app-owned immutable tables. PostgreSQL guards enforce byte receipt
integrity, bounded sequence numbers, same-batch mappings, current plan decisions,
reviewer independence, group/plan relationships and append-only events/receipts.
The fifth migration also rejects missing/null required JSON keys explicitly;
SQL UNKNOWN cannot stand in for a valid plan or transfer-receipt shape.
Reversing a guard migration is not equivalent to deleting the tables. The initial
migration's reversal destroys these new records and is not a data-preserving downgrade.

`recovery_support.populate()` creates all seven tables through real services,
including an actual file-backed canonical version, a separately authorized export
and its download receipt. `verify_restored(pins)` recreates only synthetic test
identity/policy configuration, validates source/plan/version/file/transfer pins,
checks restored immutability and denies missing current authority. The root recovery
harness owns encryption, backups and a fresh-process invocation of this adapter.

## Requirement accounting

Original inventory and specification wording remain unchanged.

| Owner point | New functional closure candidate |
| --- | --- |
| 348 | Durable operator-driven import center with native staging through usable canonical result |
| 350 | Typed structural/material/file validation, explicit blockers and reconciliation |
| 351 | Stored exact dry run; changed file/mapping/case/source invalidates execution |
| 352 | Explicit column mapping and original source-to-local identity map |
| 353 | Input replay, renamed file, source-identity and canonical duplicate handling without logical merging |
| 354 | Visible human conflicts, pinned explicit new-version choice and preservation of blank cells |
| 355 | Declared source/provenance evidence, independent verification note and no imported approval trust |
| 356 | Independent exact-plan decision, atomic groups, durable partial receipts, safe resume and final reconciliation |

These are **eight conditional development-completion candidates**, pending the
combined final evidence and independent review. Point349 remains a maintained
baseline invariant and receives no new credit. Existing parsers, hashes,
immutable storage, role boundaries and prior export capability are reused; they
are not counted again. Arbitrary historical corpus migration, imported scholarly
approvals, destructive compensation and unknown formats remain unsupported.

Point 361 is an additional conditional video-export candidate. The actual WebM
fixture passes the canonical decoder, leaves an independently authorized selected
package byte for byte, and is reimported into a fresh case with new local identifiers
and no inherited approvals. The protected browser journey now imports that actual
video ZIP, performs the independent source-use decision, and downloads the explicitly
selected package. Hosted browser completion remains a separate required proof.

## Verification

Use Python 3.13, the pinned dependencies and actual disposable PostgreSQL 17/18:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.material_import.settings -- \
  python manage.py test apps.material_import.test_formats apps.material_import.tests \
  apps.material_import.test_roundtrip apps.material_import.test_recovery --noinput --verbosity 2

# Same composition and actual protected Chrome, without a sandbox bypass:
python manage.py test apps.material_import.browser_tests --noinput
```

Initial implementation evidence: 19 parser/service tests passed on fresh owned
PostgreSQL 17.11 in 6.583 seconds. This run preceded the additional identity snapshot,
round-trip and final native integration changes and is not a final all-feature pass.
The first run exposed a missing expected-case-version argument at the canonical
write boundary; the corrected importer supplies the approved plan pins. The expiry
test initially expired its fixture identity too; it now independently refreshes
that test identity while retaining an expired import plan.

The composed backend set subsequently passed all 29 parser, importer, round-trip
and recovery-adapter tests on fresh PostgreSQL 17.11 (10.544 seconds) and 18.7
(10.237 seconds), after the canonical storage-lock integration. The adapter test
is a same-process smoke check; it does not stand in for the root's encrypted,
fresh-process recovery drill. A READ-only transfer fixture initially tried to
grant READ to a descriptive source without a file; the fixture now supplies an
actual file, preserving the canonical reader's refusal rule.
The additional real-filesystem group test passed on both majors (0.632 seconds on
17.11; 0.725 seconds on 18.7). It observes the external hash lock releasing after
the canonical file reference and group receipt commit and checks the stored bytes.

The latest integrated set passed **39/39 tests on PostgreSQL 17.11 (16.653 seconds)
and 18.7 (17.020 seconds)**. This includes the actual campaign HTTP import and
selected-export forms, decoded WebM transfer/reimport, real filesystem commit
locks, the SQL shape repair, and the three independently reviewed final-boundary
regressions. Logs: `.local/qa/import-reviewed-pg17.log` and
`.local/qa/import-reviewed-pg18.log`. The direct SQL reproducer first failed on
missing plan/receipt fields before migration 0005; those same assertions now pass.

The protected Chromium launch was attempted locally with its sandbox enabled.
The operating system rejected Chromium's process-singleton socket before any page
opened (`socket() failed: Operation not permitted`), so this is **not** a browser
pass. The log is `.local/qa/import-browser-local.log`; no sandbox bypass was used.
The hosted journey uploads an actual synthetic WebM ZIP with arbitrary columns,
uses separate authenticated import reviewer and source-use approver, opens the
canonical result, explicitly selects it and verifies the downloaded video bytes.
It writes `.local/qa/library-operations/import-browser/result.json`, three traces
and 320/1280 screenshots only after its actual assertions pass. Fresh-process
encrypted recovery and hosted browser evidence are owned by the combined runner.
