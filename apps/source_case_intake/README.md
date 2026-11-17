# V9 source case intake — lane A

Later UI additions: [V10 desk](V10_DESK.md) and [V11 source workflow](V11_SOURCE.md).
The historical V9 evidence below is preserved as recorded.

Development only: **Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED /
NOT_DEPLOYED / ACCEPTANCE_HOLD**. No webhook, provider client, real account,
outbound message, production permission or AI-written answer is introduced.

Base: PR #227, `81ccdb0f0fd25521e61ed65f098a124324139967`, checked against the
GitHub PR and `git ls-remote` before creating `codex/20261117-v9-origin`.
Ownership is exclusively `apps/source_case_intake/**`. AGENTS.md, the V6 scope
trace, V8 operational/testing instructions, current Drive MASTER and decisions
were read; `.agents/skills` is absent in this checkout. Relevant owner requirements
are D-007/016/020/028/033/036 and scope points 19, 21–23, 29–34, 37–40, 434–435,
532. This is bounded implementation evidence, not full requirement acceptance.

## Supported input contracts

These are offline adapters over fabricated objects shaped from documentation
checked on 2026-11-17, not invented provider endpoints:

| Source | Contract and accepted subset | Explicit limits |
| --- | --- | --- |
| Telegram | [Bot API Update / Message](https://core.telegram.org/bots/api#update): `update_id`, `message.message_id`, `chat.id`, `message_thread_id`, `from.id`, `reply_to_message.message_id`, exact `text` or `caption`; declared document/audio/voice `file_id` | Ordinary human messages only. Edits, sender-chat identities, external replies, albums and other media are retained for review. No downloads, signatures or webhook receiver. |
| YouTube | [Data API comment resource](https://developers.google.com/youtube/v3/docs/comments): `id`, `snippet.authorChannelId.value`, `parentId`, `textOriginal` | Original text is available only in the circumstances documented by Google; no fallback to transformed/HTML `textDisplay`. Video/conversation context is supplied by the trusted simulator, not an invented `snippet.videoId`. Missing author/original holds. Changes to the same comment ID hold as conflicts. |
| Website | Local owned `fatwa.source-case.website.v1` contract below | Simulator/server projection only; not an external API or browser-authentication protocol. |

Website envelope: `schema`, `event_id`, `message_id`, `conversation_id`,
`session_subject`, `text`; optional `display_name`, `reply_to`. These are bounded
strings; `session_subject` must come from a future trusted server session, never
an untrusted form. `simulators.py` supplies explicit examples for all three.

WhatsApp, Facebook and Instagram are **not implemented**. Their authenticated
account-specific payload variants and transport contracts have not been verified
in this lane, so no speculative parsers or API claims are included.

## Persistence and correlation

`capture(raw=bytes, context=SourceContext(...), synthetic_fixtures_only=True)`
commits a `SourceReceipt` independently. Accepted size is 1–262144 bytes. Invalid
JSON, duplicate keys, invalid Unicode and unsupported events within that bound
still retain literal raw bytes and SHA-256 with a review reason. Empty/oversized
input and unauthorized source contexts fail before persistence. No log prints raw
input, names or capabilities. An account must have the `synthetic-` namespace;
this is an explicit fixture boundary, not proof of source authenticity.

`process(receipt_id=..., token=None, synthetic_fixtures_only=True)` writes the
canonical case/evidence and `EvidenceBinding` in one transaction using the existing
`delivery_queue.synthetic_queue_atomic` composition guard. `ingest` performs both
steps and refuses a caller-owned outer transaction. A failed apply leaves the
receipt PENDING; retrying `process`/`ingest` is safe. Capture does not claim delivery.

Exact raw replays return the same receipt, never another capability. Changed
bytes for the same account/source/event create a separate immutable review receipt;
they cannot overwrite or reapply the original. Distinct event IDs carrying an
already-bound source/message are also held. Source/account advisory locks and
database unique constraints cover concurrent retries. Message keys include source,
account, conversation and message ID; requester keys include source, account and
sender ID, never display names. Thread identity is checked separately.

A first standalone message creates one canonical `casework.Case` using
`casework.intake_case`. An explicit reply can append through `casework.add_followup`
only when its existing parent is bound in the same account, conversation, thread
and sender identity, with a current capability for that exact case. No source
matching mints capabilities. Missing parents, absent capabilities, changed senders
or threads, and unthreaded later messages from an already-known conversation/sender
create review tickets. New facts preserve canonical evidence history and invalidate
the previous human approval through the existing service.

`resolve_review` requires an explicit synthetic MUFTI directory scope
`source-intake-review`, an action (`NEW_CASE` or `FOLLOWUP`), and a human note.
FOLLOWUP also requires target case scope, current capability and an existing
same-origin identity binding. The human may explicitly split an ambiguous message;
different senders cannot be joined to an existing case. The immutable ticket remains
after resolution; its binding records reviewer/provider/epoch/note. Edited source
events and raw conflicts cannot be resolved by silently substituting new text.
Review authority is rechecked before commit. No organizer grants are invented.

## V8 attachment contract

`attach_fixture(receipt_id, source_file_id, token, raw, filename, media_type,
synthetic_fixtures_only=True)` accepts only a declared file ID on an already-bound
receipt and a valid capability for its case. It calls `case_attachments.upload`
and adds an immutable `AttachmentBinding` to that resulting attachment. The source
file reference identifies the fabricated input; it is not proof that a remote file
was fetched. All original metadata remains in the raw receipt.

V8 remains responsible for type/size validation, private storage, evidence version,
authorization and rollback. Its attachment `source` stays `REQUESTER_UPLOAD` because
the existing contract is used unchanged; `AttachmentBinding` supplies the external
origin relationship. Replays validate bytes/name/type; changed content is rejected.
No new storage adapter, size increase or malware-scan claim is made. Captionless
media remains held for review; it does not become a fabricated question.

## Final integration contract (integrator-owned changes)

1. Register `apps.source_case_intake` in the synthetic campaign profile, run its two
   migrations, and keep `FATWA_SOURCE_CASE_INTAKE_ENABLED=False` by default. Local
   test profile is `apps.source_case_intake.settings`; opt in only for the demo/tests.
2. For the private mufti desk call `services.staff_origins(case_id, subject_id,
   provider, synthetic_fixtures_only=True)` after the existing login. Its result is
   ordered by canonical evidence version. Pass it as `source_origins` and include
   `source_case_intake/origins.html`. It shows literal question/name/source/IDs,
   thread/reply position and raw digest with escaping. Do not expose it publicly.
3. **Do not display legacy `CaseSource.channel == WEBSITE` as the actual provider
   for these cases.** V8's constraint permits only WEBSITE and was not changed in
   this lane. Here it represents the reused internal intake service; the immutable
   `EvidenceBinding.receipt` and `staff_origins` are the actual inbound-origin
   authority. Integrator must overlay the desk source label with this projection.
4. `staff_raw(receipt_id, subject_id, provider, ...)` returns bytes only after the
   bound case's existing scope check; unbound receipts require explicit review
   scope. If adding a download route, reuse private no-store/noindex/nosniff and
   attachment disposition. There is no raw route supplied here.
5. `review_queue` exposes up to 100 unresolved tickets to the explicit review scope.
   A review UI, pagination and assignment are integration/future work; this lane
   provides the services and immutable audit, not a shared desk edit.
6. For the connected synthetic journey, call `simulators.telegram(document=True)`,
   `services.ingest`, then `attach_fixture` with the returned ephemeral token.
   Continue with canonical casework/research/answer services using `case_id`.
   The returned token is never stored by this app. Losing it requires the existing
   trusted recovery workflow; replay does not reveal it again.

No URL registration is required or supplied. No changes were made to casework,
case_attachments, config, shared templates, root dependencies, CI or AGENTS.md.
The app-owned template fragment is ready for integration, not claimed as a live
mufti desk route or a browser-tested user journey.

## Run and evidence

Use Python 3.13, pinned `requirements-dev.txt` and the repository's fresh owned
PostgreSQL helper. These commands do not contact an installed/shared database:

```sh
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.source_case_intake.settings -- \
  .venv/bin/python manage.py test apps.source_case_intake.tests --noinput --verbosity 2

.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.source_case_intake.settings -- \
  .venv/bin/python -m apps.source_case_intake.demo
```

Local 2026-11-17: **23/23 PASS**, PostgreSQL **17.12**, Python **3.13.16**, Django
**5.2.18**. Covers three source create/reply journeys; exact bytes; concurrency;
same-name/account/conversation/thread isolation; edits/conflicts/missing originals;
unresolved/unthreaded human correlation and audit; review authority changes;
revoked/foreign capabilities; approval invalidation; V8 attachment rollback/dedup;
database immutability/cross-case denial; populated guard reversal/reapplication;
template escaping and RTL markup. No unaffected test suite was manually repeated.
The owned-cluster system check and migration-drift check passed; Ruff lint/format
and `git diff --check` passed. The final demo produced CREATED then FOLLOWUP for
Telegram, YouTube and website, each pair sharing its own case reference.

Historical failures preserved: the first demo failed with
`GUARD_BEFORE_TRANSACTION_REQUIRED` because plain `transaction.atomic` could not
compose guarded casework calls. Fixed by reusing the existing guarded queue unit;
no guard monkeypatch/bypass. The first test-discovery command targeted a namespace
package and failed before running tests; the explicit `.tests` module fixes it.
The initial focused run then passed 20/20; the final 23-case run includes those
cases and three added checks, not 43 independent acceptance claims.

PG18, campaign CI, actual desk/browser integration and production transport are
**NOT_RUN in this lane**. The integrator owns the one combined PG17/18/Chrome run.
No engineering completion percentage is inferred from these tests or line counts.
