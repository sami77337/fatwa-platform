# Public answer reader tools — synthetic implementation of owner point 278

Original point 278 is **«تدعم Save/Share/Print/Download وفق السياسة.»**
The relevant contracts are SPEC-U09-020, SPEC-U11-024 and D-057, together with
U08-025's boundary on personal copies. This app adds the four missing native
controls for an exact currently approved public answer. It does not claim the
preexisting publication reader, source metadata, private answer export or offline
library as new work. It makes no production policy acceptance claim.

## Four explicit capabilities

`ReaderToolsAuthority.grant(publication_id, content_sha256, action)` returns an
immutable `ReaderGrant`, or `None`. A grant pins the exact public edition and
content hash, one action, the current scoped MUFTI authorizer's trusted provider,
subject and authentication epoch, and a finite deadline at most one hour away.
`projection_epoch()` must be a pure atomic snapshot of every grant, authorizer
binding and deadline input. The directory must expose its own current pure
`projection_epoch()`. Neither reading permission nor an earlier saved reference
supplies a missing grant.

| Action | Native behavior | Data retained or returned |
| --- | --- | --- |
| `SAVE_REFERENCE` | Explicit button saves a reference to this device; the local list rechecks the exact version before showing its current title. | Only public publication UUID, content hash and version number in local storage; no title, answer, file, private identifier or permission. |
| `SHARE_LINK` | Rechecks current permission, then offers/copies the existing public URL. | A public publication URL; no message is sent and no recipient obtains additional permission. |
| `PRINT` | Opens a readable print layout; the native print button rechecks the exact content permission immediately before `window.print()`. | The authorized published text and allowed display references. A denial clears the printable content. |
| `DOWNLOAD_TEXT` | Downloads an exact UTF-8 personal text copy. | Published text, permitted display references and the public URL; no audio, source file, requester history, internal notes or archive. |

The download filename uses only the public edition UUID and number. References
come from the existing public display projection; this tool grants no source file
download/export or offline use. Source files keep their independent authorities.
The browser's own printing, screenshots and saving of already received public
content are outside the scope of these policy-bound application controls.

The local saved list is intentionally not an account, server bookmark table or
offline cache. It explains that references remain on this device and do not
promise synchronization. A withdrawn or inaccessible saved publication shows a
generic unavailable label, without replaying its old title/text. Each reference
can be removed explicitly. Another browser context receives no saved list.

## Current source and response boundary

Every descriptor, print page and text response opens the exact publication's
existing guarded text projection, with optional recordings disabled. The source
reader retains canonical publication, citation dependency and original-media
guards through actual rendering or byte assembly. The tool boundary pins policy
object identity, directory object identity, their pure generations, source rows
and deadlines before callbacks. It repeats grant/actor checks after rendering,
then performs a final pure check after all source contexts exit. Late revocation,
same-value policy replacement, changed source or expiry rejects the response.

Read access may remain available when an individual tool is denied. The unavailable
control is omitted and its endpoint independently returns 404. An unavailable
publication cannot be revived through bookmarks, print, share or download.

## Integration contract

Shared wiring is supplied separately by the coordinator:

- App `apps.public_reader_tools`.
- `FATWA_PUBLIC_READER_TOOLS_ENABLED = False`.
- `FATWA_PUBLIC_READER_TOOLS_AUTHORITY = None`.
- `config.campaign_urls` includes `apps.public_reader_tools.urls`.
- Existing public publication detail pages link to **حفظ ومشاركة وطباعة الجواب**.
- `_allow_library_reader_tools` adds only same-origin script and connection
  sources to the existing restrictive preview CSP. No inline/eval, external
  origin, worker or media exception is added by this app.

The exact routes are `/library-preview/reading/<public-publication-uuid>/` and
its `save-reference/`, `share-link/`, `print-permission/`, `print/`, `download/`
children. `/library-preview/reading/saved/` serves the local list shell;
`tools.js` and `tools.css` are bounded static assets under the same prefix. All
routes retain the existing loopback synthetic GET/HEAD and no-store guard.
Print styling explicitly remains light and legible under a dark system preference.

There are **zero new SQL tables, migrations, functions or triggers**. No server
write occurs when saving or deleting a device reference. The only mutations used
by recovery fixtures are real existing canonical/publication services.

## Evidence

`apps.public_reader_tools.tests` contains 14 native/real-PostgreSQL regressions.
They cover connected controls, separate action denials, exact personal-copy bytes,
current actor scope and epochs, wrong hashes/versions/deadlines, policy identity
replacement, late grant/source callbacks and actual render-time withdrawal with
transaction rollback. They passed on PostgreSQL 17 and 18. The focused recovery
label is `apps.public_reader_tools.test_recovery`. The combined 15-test set also
passed on PostgreSQL 17 and 18 after the recovery helper was added.

Protected browser class:
`apps.public_reader_tools.browser_tests.ReaderToolsBrowserTests`.
Its proof path is
`.local/qa/functional-continuation/reader-tools-browser/result.json`.
It uses actual sandboxed Chromium, starts at the existing publication page's
native link, saves/reopens/deletes references, checks isolation in another browser
context, uses the native share/download/print controls, observes the real
`beforeprint` event and saves an actual printed PDF. It withdraws the publication
through authenticated native forms and checks the saved reference and all tool
routes afterward. It captures 320/1280 RTL screenshots and three traces. Execution
is reserved for the protected hosted gate; the class's presence is not a PASS.

`recovery_support.populate()` pins an existing real approved publication, exact
download bytes and original audio. `verify_restored(pins)` rebuilds only synthetic
trust in the fresh process, checks the exact public copy, proves **eight** actual
denials (missing authority/directory/publication grant, revoked authorizer, and
each of the four missing action grants), repeats positive reads and checks that
all pinned source rows and original bytes remain unchanged. Device bookmarks are
not claimed as server-restored data. An encrypted fresh-process run remains a
separate coordinator gate.
