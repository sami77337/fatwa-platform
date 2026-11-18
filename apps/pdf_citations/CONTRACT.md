# V14 PDF citation integration contract

Branch `codex/20261118-v14-pdf-citations`, based on PR #232 at
`1f08cbb7166f70ec340c495da33ccfc1eda9534e`. Ownership is limited to this app and
`apps/timed_citations/`. Shared settings, URL admission, approval/use wiring and
CI are the coordinator's responsibility. This is synthetic development work.

## Function and identity

`inspect_source` reads an existing `CaseAttachment(kind=pdf)` or
`AnswerPart(kind=FILE, media_type=application/pdf)` within the authorized case.
It verifies the original bytes through the existing private asset services and
isolated parser. No storage backend, file copy, upload API or scientific text is
introduced. The pin includes canonical kind/ID, SHA256, exact owner version,
metadata digest, filename, media type, size and verified page count.

The version is the attachment's original `CaseEvidence.version` or the answer
part's original `AnswerRevision.revision`. It is never a floating "latest"
pointer. The original parser's bounds remain in force (192000 bytes, 1–10 PDF
pages, no encrypted/active-content document). Every authorized open revalidates
both the bytes and the recorded parser metadata. This is not a virus-scanner
claim, OCR, book text, transcription, global taxonomy or inference from TOC 622.

`propose(source_pin, page_number, printed_label='', printed_confirmed=False, ...)
` pins a physical 1-based page within that count to the current unreviewed
answer/evidence. A non-empty printed label requires an explicit human assertion;
no automatic physical-to-printed offset is inferred. The assertion's actor,
provider, epoch and timestamp are stored. Software checks the physical bounds;
it does not independently prove the truth of a human's printed-label claim.
`act(..., action='CONFIRM', confirmed=True)` is a locator review, never scholarly
answer approval. `WITHDRAW` remains available to scoped authorized staff after
source rights lapse, without deleting the source, question, answer or history.

Corrections use `replaces_id`, an append-only successor in the same series/case.
Only one concurrent successor wins. Approved/reviewed answers cannot acquire or
change locators in place. A new answer does not inherit old locators. A human may
explicitly select a still-authorized old original when creating a correction;
that remains an exact old original, never a silent replacement. Withdrawn and
superseded locators cannot open; stale-answer locators cannot open as current.

## Rights and privacy

Reuse `FATWA_RESEARCH_WORKSPACE_RIGHTS` implementing the existing
`apps.timed_citations.rights.TimedMediaRights` interface (the historical class
name is retained to avoid a second policy system). Require **READ_MEDIA and
CITE separately**, for exact canonical `Resource(kind, id, sha256)`, provider,
subject, epoch and case scope. READ_MEDIA is the existing media-read operation;
a book/TOC READ grant, file import, relationship or locator confirmation grants
neither of these rights. Each exact action supplies an aware current
`grant_deadline`; checks occur before and after byte reads, after authority
callbacks and at projection exit. The configured authority must serialize
revocation with the canonical case lock, as already required by that interface.
No default media rights adapter or wildcard grant is provided.

The desk redacts unavailable source names, physical/printed labels and reasons.
Correction reasons also require the predecessor's source rights. The page has no
public/library/requester route. Knowing a locator UUID is insufficient. Original
PDF bytes require a current scoped staff session and current rights on every
GET/HEAD; URLs contain neither case capability nor rights token. Source-form
pins are signed but are not authorization.

## Required shared wiring — do before enabling

1. Keep the existing `apps.timed_citations` dependency installed. Install
   `apps.pdf_citations`; apply `0001_initial` and `0002_integrity`.
   Keep `FATWA_PDF_CITATIONS_ENABLED=False` by default. Activation additionally
   requires `FATWA_PRODUCTION=0`, owned synthetic database admission and existing
   private-media/answer/case/identity/rights prerequisites. `settings.py` and
   `urls.py` are owned standalone test compositions, not production profiles.
2. Dispatch `views.ACTIONS` (`pdf_desk/propose/confirm/withdraw/open/preview`)
   through the existing CSRF-protected staff POST endpoint. Add the desk action
   to the current-case UI. Render `pdf_citations/desk.html` inside that journey.
3. Admit these exact loopback GET/HEAD routes, preserving maintenance admission,
   request budget, no forwarded host/address, no query arguments and default
   denial for every other route:
   - `/casework/staff/pdf-citations/<uuid>/document/` → `views.document`,
     name `pdf_document`;
   - `/casework/staff/pdf-citations/<uuid>/review-document/` →
     `views.review_document`, name `pdf_review_document`.
   `guard.PdfCitationGuard` is the standalone composition example. Response
   headers reuse canonical private `_inline`: sandbox CSP, SAMEORIGIN, nosniff,
   private/no-store, no archive. HEAD reauthorizes just like GET. Native `#page=N`
   is a viewer navigation hint, not a grant limited to a page. Full-file READ is
   required; the link never exposes a publicly accessible source.
4. **Mandatory approval/use guard:** under the existing authorized canonical
   case lock call `integration.require_for_answer(answer, actor=..., provider=...)`
   before recording a scholarly approval. For later use call
   `integration.require_for_answer(answer)` to resolve the recorded scholarly
   approver, provider and exact epoch. A missing/pending/withdrawn citation,
   current-source mismatch, revoked/expired READ_MEDIA/CITE or changed authority
   fails closed. `services.for_locked_answer` is its lower-level read hook.
5. Feed the returned earliest expiry into the coordinator's existing
   `_answer_use_boundary` collector, including every outer/nested response and
   transaction. Do not perform a new rights callback after final identity checks
   just to collect deadlines. Follow `_answer_timed`'s V13 call sites for review,
   private release/portal, delivery preparation/use, editorial publication and
   library projection. A requester/anonymous principal must never impersonate
   the scholarly actor. This guard is an additional veto, never release or
   publication permission. Failed use preserves the historical answer/approval.
6. Do not skip persisted PDF rows merely because the editing flag is off or the
   app is omitted after restore. `require_for_answer` detects retained rows even
   without the app registry and denies. For truly annotation-free answers it
   preserves existing behavior. Missing/unavailable schema must not be caught
   and converted into an allowed result. Include both new append-only tables in
   recovery relationship verification and the integrated synthetic journey.

This branch does **not** patch the canonical approval/use call sites. Enabling
PDF annotation without steps 4–6 would leave a bypass. Keep the feature closed
until the coordinator connects and tests those paths on the combined branch.

## Audio preview extension

`timed_citations.services.open_audio(..., review=True, context_ms=0)` accepts an
integer 0–5000 ms of context on either side, clamped to the measured duration.
It returns `preview_start_ms/preview_end_ms`, original `start_ms/end_ms`, exact
`source_version/source_sha256`, and the same authorized original bytes. Context
is forbidden outside review; boolean/negative/oversize/non-integer values deny.
The native form offers 0/1/3/5 seconds. The saved locator and its fingerprint do
not change. Existing route rights, expiry, current-answer and withdrawal checks
are retained; no public link, new source version or permission is created.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No completion
estimate or acceptance claim, main merge, production action or external send.
