# V13 P1-B — exact private timed citations

Base: PR #231, `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`, verified using
GitHub PR metadata and the remote integration ref. Branch
`codex/20261118-v13-timed-citations`; only `apps/timed_citations/**` is owned/changed.
AGENTS, V6 scope trace, V12 P1 integration and the preserved D-062/D-068 decisions
were read. This is a synthetic development slice, **not acceptance**.

## Usable behavior

A scoped MUFTI can select an existing private audio attachment or authored answer
part, enter start/end in integer milliseconds, save a proposal, listen privately,
explicitly confirm the locator, and open the confirmed original at its time
fragment. The desk displays the exact source version, duration and hash. Native
forms retain the selected case. No ASR, generated transcript/quotation, remote URL
fetch, media transcoding, new media store, or book text is introduced.

The original remains in `case_attachments` / `answer_media` and their existing
`private_media` storage adapter. Every use rechecks canonical ownership, bytes,
checksum and existing parser metadata. Duration is measured again using the
existing isolated validator; milliseconds are conservatively floored from that
measurement, never taken from a browser/form claim. Range is
`0 <= start_ms < end_ms <= verified_duration_ms <= 120000`. Existing 192000-byte
and supported audio-format limits remain unchanged.

Each citation pins an owner UUID, owner version (attachment Evidence version or
AnswerRevision number), SHA256, parser metadata digest, duration and bounds. A
changed pin fails closed. A newer recording never replaces that pointer. An old
recording can be cited again only by explicit human selection/correction with its
exact old pin and current rights; it is never inferred from equal filenames/hash.

Citation proposals/confirmation require the current unreviewed answer and current
Evidence. They cannot modify an approved or already-decided answer. Updating the
answer makes the old citation non-current and unopenable here. Explicit correction
on a new draft may bind to the deliberately selected old original. Corrections
append a new series revision with a protected predecessor; withdrawal appends an
action, including when rights have been lost. No question/answer or citation
history is deleted, no approval or release is inferred, and there is no automatic
citation cloning onto a new answer. PostgreSQL guards reject history mutation,
cross-case/owner/version/range mismatch and competing successor revisions.

Source metadata, times and reasons are redacted when the source cannot currently
be read/cited. A correction reason is also redacted when its predecessor loses
rights, since it may mention that recording. The private history retains state
and event identity for the authorized case reviewer. Nothing is added to a public
library, requester response, delivery plan or publication projection.

## Coordinator integration contract (shared files not edited)

1. Install `apps.timed_citations` alongside the existing campaign applications;
   apply `0001_initial` and `0002_integrity`. Enable only in the synthetic profile
   with literal `FATWA_TIMED_CITATIONS_ENABLED=True`, `FATWA_PRODUCTION=0`, existing
   owned-database/maintenance/identity gates and source app opt-ins. Default is
   closed. `settings.py` is an owned standalone test profile, not a shared change.
2. Dispatch POST `views.ACTIONS` to `views.workspace` on the existing staff route.
   Include the two protected GET/HEAD audio routes from `urls.py`. They resolve
   citation UUIDs, not raw storage paths. The owned `TimedCitationGuard` is the test
   composition: it preserves the existing guard elsewhere, loopback host/remote
   checks, forwarded-header rejection and the existing read request budget. The
   audio views repeat loopback/identity/source authorization. Integration must
   explicitly admit these routes in its shared composition; no anonymous bypass.
3. Extend the **existing configured** `FATWA_RESEARCH_WORKSPACE_RIGHTS` policy with
   `rights.TimedMediaRights`. It remains a `ResearchRights`; no parallel rights
   records or permission store is created. Supply literal True for both
   `READ_MEDIA` and `CITE` on the exact existing Resource(kind, owner UUID, SHA256),
   current case/provider/subject/epoch. `grant_deadline(**same_args)` must return an
   aware, verifiable conservative expiry for that exact grant or None to deny.
   Policy revocation/changes must serialize with the canonical case lock.
   Successful deadlines join the existing source-rights projection expiry guard
   and are checked before transaction commit / composed read completion. The
   owner UUID identifies the immutable version; it is not an access capability.
   Legacy media READ_MEDIA policies, `SourceRightsAdapter(media_rights=...)` alone,
   missing expiry, and source registration/import do **not** confer audio CITE.
   A concrete non-synthetic licensing authority is not provided or invented here.
4. `services.inspect_source(...kind, source_id)` returns the exact `source_pin`.
   `propose(...source_pin, start_ms, end_ms, reason, expected_revision,
   expected_evidence_version, replaces_id=None)` binds it to the current draft.
   `act(...citation_id, action=CONFIRM|WITHDRAW, confirmed=True)` records the human
   action. `open_audio(...citation_id, review=False)` returns the authorized whole
   original and bounds. `review=True` is a private preview of a current draft,
   never confirmation. Native `#t=start,end` is navigation, not a claim of byte
   clipping or a permission limited to just that interval. No HTTP Range support
   is claimed; the original response explicitly advertises `Accept-Ranges: none`.
5. **Required before using these annotations in canonical approval/delivery:**
   call `for_locked_answer(answer=..., actor=..., provider=...)` under the current
   authorized case transaction before approval and each downstream use. It rejects
   pending/withdrawn/non-current references and revalidates exact source rights and
   expiry. Integrator owns these call sites. Existing `case_citations` remains
   canonical for book references; this module does not impersonate a book citation
   or replace the answer approval service. Canonical answer code is untouched and
   is not claimed to call this hook yet. No private/public release of timed
   citations is implemented. Keep the feature closed until shared wiring and
   independent security review pass.
6. Browser recording adapter: accept only an actual immutable `CaseAttachment` or
   `AnswerPart` committed through the existing media validation/storage service,
   then pass `kind="ATTACHMENT"|"ANSWER_MEDIA"` and its UUID to `inspect_source`.
   Preserve WAV/other supported original bytes; no browser duration, object URL,
   temporary recording ID, guessed fields or new version redirect is accepted.
   The browser capture contract and evidence were read directly from remote SHA
   `6e978e7cff7590ea8e78fde7e377c43a36f3ef9a` on
   `codex/20261118-v13-audio-capture`, without merging or copying that app. Its
   accepted original is `capture.wav`, PCM16LE mono at 8000 Hz, at most 80000
   frames/10 seconds/160044 bytes. Its canonical owner and parser metadata match
   this adapter exactly. This app uses the actual retained duration, not that
   maximum: a 7001-frame recording is bounded to 875 whole milliseconds, while
   the 80000-frame recording is bounded to 10000. Source zero is the first sample
   of the accepted WAV, not a guessed physical microphone timestamp. Capturing,
   accepting and saving remain upstream's independent UI/service workflow.

The desk keeps its own revision history, not a second case, answer, media or
scholarly authority. Existing publication/rights gates remain authoritative.
Book 622 remains a TOC only; this app does not broaden source permissions.

## Evidence and limits

Python 3.13.5, Django 5.2.18; fresh owned loopback databases through
`infra/dev/with_casework_postgres.py --settings apps.timed_citations.settings`.
Only generated 0.1-second silent WAVs, synthetic case identities and explicit
short-lived exact-media grants were used.

- PG17.12: 11/11 initial completed service/HTTP tests PASS (4.536s); three added
  expiry/concurrency/database-guard tests PASS; added predecessor-note privacy
  test and affected HTTP test PASS. **15 distinct functional tests** have passing
  evidence across those focused batches, without repeating unrelated tests.
  One additional browser-capture contract compatibility test passed on both
  majors after the upstream contract arrived: **16 distinct functional tests**
  now have passing evidence per major across the recorded batches.
- PG18.7: **15/15 PASS**, 6.627s (`manage.py test apps.timed_citations.tests`),
  then the added actual-frame-duration/source-version compatibility test **1/1 PASS**.
  That test exercises both canonical attachment and answer-part persistence with
  7001 and 80000 generated nonzero PCM frames, verifies byte hashes, rejects a
  bound 1ms beyond the measured duration and rejects an old citation after the
  next answer revision. It is a contract compatibility test; a combined browser
  capture → citation journey remains for integration.
- Chromium154.0.8037.57 on PG17: **1/1 functional PASS**, 3.266s; native parser
  duration=0.1, exact authorized bytes, temporal fragment, RTL at 360px, keyboard
  focus, no page errors/external requests, withdrawal immediately returns404.
  This local run used `FATWA_TEST_BROWSER_NO_SANDBOX=1`. It is **not protected
  Chrome acceptance**; the protected browser run is still required in integration.
- System check and migration application pass on both majors. PG18 model drift
  check and rollback/reapply of the immutable SQL guards: PASS. Ruff: PASS.

Historical failures are retained as evidence: the first HTTP test used the old
fixture URL profile and failed before it could find its CSRF field; its profile
was corrected and the affected test passed. Protected Chromium startup aborted
because this environment's SUID sandbox helper is not configured; the journey
was NOT_RUN in that attempt. Later local browser harness failures were CSP
rejection of `wait_for_function` string eval, then a synchronous ORM assertion
inside Playwright's event loop. The helper now awaits a native media event and
checks the ORM after leaving Playwright. No application CSP, Django async safety
check, or sandbox configuration was weakened to hide these failures; the
separate unsandboxed functional run is explicitly attributed above.

Security verification includes invalid/boolean/nonfinite times, duration overflow,
forged source/version/hash pins, non-audio/unverified content, stale answer/no
silent recording substitution, append-only correction/withdrawal, READ_MEDIA vs
CITE, missing/malformed configuration, actual expiry and expiry during response
composition, mutation rollback, cross-case/epoch revocation, predecessor privacy,
concurrent corrections, CSRF, anonymous/forwarded/nonloopback denial and no-store.
A human-confirmed locator is **not** a fatwa approval or publication permission.

Gate B **NOT_PASSED**, C/D/E **HOLD**, Phase01 **BLOCKED**, **NOT_DEPLOYED**.
No main merge, production/real keys/data, real external send, unapproved U03,
automated scholarly approval, Meta assumptions, GitHub configuration change,
completion estimate or acceptance claim.

## V14 bounded listening context

The V14 change adds an optional `context_ms` (integer 0–5000, review only) to
`open_audio`. Playback bounds are clamped to the measured original duration;
original citation bounds, hash and version remain unchanged. Native review forms
offer 0/1/3/5 seconds and show both ranges and the exact original fingerprint.
Rights/scope/expiry/current-answer/withdrawal guards remain in force. This adds
no publication permission or source substitution. The updated browser journey
selects one second of context around a 0.1-second fixture and verifies that the
stored 10–90ms locator did not change. V13 historical evidence above is retained.
See `../pdf_citations/CONTRACT.md` and `../pdf_citations/EVIDENCE.md` for the shared
V14 delivery contract, new focused evidence and environment limitations.
