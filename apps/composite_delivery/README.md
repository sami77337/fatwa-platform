# V9 E — synthetic composite delivery preparation

Based on PR #227, verified remote head
`81ccdb0f0fd25521e61ed65f098a124324139967`. Owned branch:
`codex/20261117-v9-composite-delivery`. All changes are inside this app.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
No external send, production signer/grant, AI approval, public route, real data,
main merge or sub-PR. Provider outcomes are offline simulations only. Existing V8
and earlier failure/evidence records remain unchanged.

## Implemented contract

Canonical Case, AnswerRevision, human CaseDecision and AnswerManifest remain
sources of truth. CompositeDelivery is one immutable decision-to-queue binding,
not a second outbox. The existing planner, signed return approval, ApprovalClaim,
DeliveryIntent/Attempt, provider verifier, receipt store and audit chain perform
all delivery state work. No engine files changed.

The ordered text/file/audio/image plan pins each part's UUID, ordinal, original
SHA-256, size, MIME/metadata, current revision, facts and human decision. The signed
plan also binds the return target and full capability values, including changes
without a profile version bump. Kind, text length, media size/MIME and receipt
support are checked. Any unsupported part stays visible with a reason and holds
staging of the entire plan. There is no automatic split, omission, public link or
channel substitution.

A current scholarly approval permits preparation; a separate Ed25519
APPROVE_RETURN_TO_ORIGIN receipt permits staging. Exact approver, current role,
case scope/auth epoch, answer, facts, manifest and capabilities are rechecked
around operations. Atomic staging binds all parts. One decision cannot be rebound
under another return approval to resend successes.

ACCEPTED stays SENT_UNCONFIRMED. Completeness requires signed DELIVERED evidence
for every correct part and attempt. Events bind plan, intent, ordinal, envelope
digest and attempt-token hash. Replay is idempotent; foreign/altered/unsigned
receipts cannot prove complete delivery. Partial success, failure and unresolved
leases remain distinct. Only unattempted STAGED parts can be reserved: successful,
failed, accepted and unresolved parts are never automatically retried. Reading is
never claimed.

## Integration handoff

1. Coordinator registers `apps.composite_delivery` in the owned synthetic campaign
   settings and applies `0001_initial` / `0002_binding_guards`. Shared config was
   not edited. The guards depend on `answer_media.0003_media_metadata_guards` and
   existing case/queue migrations. SQL rejects foreign case/answer/manifest,
   approver or part count and makes the binding immutable.
2. Default `FATWA_COMPOSITE_DELIVERY_ENABLED=False`. Opt in only for an owned
   synthetic DB with FATWA_PRODUCTION=0, existing ownership settings and explicit
   `synthetic_fixtures_only=True` service arguments.
3. Server-only `FATWA_COMPOSITE_DELIVERY_CAPABILITIES` is a callable receiving
   the validated immutable inbound source (`telegram`, `youtube`, `website`),
   or the legacy canonical `case.source.channel` for pre-import cases and returning `ChannelProfile`. Example:

   ```python
   ChannelProfile(
       Capabilities(
           "composite-simulator",
           "synthetic.v1",
           frozenset({"text", "document", "audio", "image"}),
           6000,
           True,
       ),
       192000,
       frozenset({"text/plain", "audio/wav", "application/pdf", "image/png"}),
   )
   ```

   Real provider names are rejected. Never accept profiles from browser fields.
   Missing readers fail closed; changing/revoking capabilities stops old plans.
4. Internal staff APIs all take case_id, subject_id, trusted identity provider and
   the synthetic acknowledgment:

   | API | Additional input / result |
   | --- | --- |
   | prepare_composite_delivery | Full metadata, evidence, plan, plan_sha256; REQUEST_NOT_APPROVED; render step reasons for REQUIRES_HUMAN_DECISION |
   | stage_composite_delivery | Signed receipt and Ed25519ApprovalVerifier; all-or-nothing existing queue staging |
   | reserve_composite_part | worker_id, verify_worker, verify_receipt; existing WorkerLease or None |
   | resolve_composite_part | lease, verify_receipt; internal exact bytes/metadata and envelope_sha256, no URL |
   | record_composite_event | lease, event, provider verifier; existing signed receipt adapter |
   | reconcile_composite_timeouts | Explicit server-clock quarantine of expired leases in this plan only; no resend |
   | composite_status | Provider verifier; per-part states, human action, verified count, evidence_status, delivery_verified, read_confirmed=False |

   Context changes raise fixed conflicts: render stale/unavailable, never cached
   success. Existing synthetic fixture signers may supply test return approvals;
   this app contains no MUFTI signer.
5. `OfflineProviderSimulator(synthetic_fixtures_only=True)` creates an ephemeral
   in-memory provider key and exposes `.verifier`. Its `.event(lease=..., part=...,
   reported="ACCEPTED"|"DELIVERED"|"FAILED")` verifies canonical part identity and
   content metadata, then returns a signed event without recording/sending. Feed
   that event into record_composite_event. No transport or persisted key exists.
6. Staff-only inclusion:
   `{% include "composite_delivery/status.html" with status=composite_status %}`.
   Supply the freshly authorized projection. Arabic labels distinguish acceptance,
   failures, unresolved outcomes and aggregate evidence with explicit synthetic
   limits. Coordinator owns HTTP/CSRF/loopback dispatch and final Chrome checks.
   This lane adds no route or requester projection.
7. Track D seam: delivery uses `answer_media.manifest_for_locked_answer` and
   `answer_media.staff_read` for media; text uses canonical manifest text. Returned
   metadata/hash/length are verified. **The delivery service never reads the
   original storage column directly.** Storage can change behind these APIs.
   Media read flags must be enabled in the synthetic composition; storage failure
   never produces delivered status.
8. Preserve the old casework.delivery multipart rejection and requester portal
   availability semantics. This new internal adapter reuses the same engine; it
   does not silently override old text-only transport or imply that private
   availability is external delivery.

## Focused evidence

Python 3.13.16, pinned repository dependencies, fresh owned PostgreSQL **17.12**:

```sh
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.composite_delivery.settings -- \
  .venv/bin/python manage.py test apps.composite_delivery.tests --verbosity 2
```

- Initial group: **12/12 PASS**, 7.716s.
- Expanded group after storage-reader integration and simulator hardening:
  **17/17 PASS**, 9.292s.
- Final refinement identifies unsigned delivery reports as human-action items per
  part even before the entire plan finishes. Only the four affected projection /
  journey tests were rerun: **4/4 PASS**, 3.297s. The other 13 were unchanged and
  not rerun. These groups overlap; do not add the counts.
- Final PostgreSQL migrations/bootstrap, Django check and migration drift check:
  **PASS**, no changes detected. Ruff and diff whitespace checks: **PASS**.
- Tests cover text/file/audio identity, kind/MIME/size/text/receipt capability gaps,
  wrong/unsigned/stale approval, capability drift without version bump, part/attempt/
  case receipt substitution, replay, accepted vs delivered, partial failure,
  unresolved reconciliation, no retry, new facts/answer, role/epoch/scope/production
  gates, rollback after scope revocation, SQL cross-case/immutable binding guards,
  populated guard migration reversal/reapply, simulator content forgery, storage
  failure/hash mismatch and Arabic template rendering.
- No test failures in these runs. Setup initially hit the read-only default uv
  cache; installation succeeded under /tmp. Offline makemigrations warned that
  default port 1 had no DB; subsequent real PostgreSQL migration execution passed.
  Initial clone command found the pre-provisioned directory; fetching/checking out
  the verified V8 SHA in that repository succeeded. No history was overwritten.
- **NOT RUN here:** PG18, routed UI and Chrome; coordinator owns final integrated
  PG17/18 and browser verification. Unaffected suites were not rerun. No external
  account, transport API or deployment was exercised.

Current bounds remain eight immutable parts and V8 file/parser limits. Long text
needing segmentation, unsupported formats/receipts and capability drift require
human intervention. A bound decision cannot be rebound under a new profile: use a
reviewed new answer/decision. Private portal release is a separate authorization.
No malware scan, production readiness, owner acceptance or completion percentage
is inferred.
