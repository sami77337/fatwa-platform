# Private synthetic case attachments

Requester uploads a small fabricated UTF-8 `.txt` file from the existing private
case session. The original bytes, SHA-256, byte count, validated text media type,
safe filename, source, requester identity and timestamp are stored in PostgreSQL.
There is no static/media URL or filesystem path. Scoped MUFTI users see the same
attachment from the same case; another requester or case cannot preview/download it.

Every upload appends one `CaseEvidence(FOLLOWUP)` and its existing case event inside
the case lock and transaction. The attachment binds to that exact evidence version.
New facts clear approval and invalidate its delivery basis through the existing
case service. Stale/replayed forms cannot append again. A pending clarification
blocks upload until the requester explicitly replies to it.

The PostgreSQL guard rejects updates/deletes, verifies hashes/size and rejects
cross-case bindings. Failure rolls back attachment, evidence and event together.
Capability revocation and scoped staff identity checks reuse the existing core.
Responses are private/no-store/noindex with CSP and nosniff. Native forms require
CSRF. Upload proofs bind browser, capability, case and revision. Preview text is
escaped; download forces Content-Disposition attachment.

## Integration

Register `apps.case_attachments`, apply migrations to the owned disposable
synthetic database and explicitly set `FATWA_CASE_ATTACHMENTS_ENABLED=True`.
The flag is false by default. No production/public setting is enabled.

Existing guarded `/casework/status/` dispatches `REQUESTER_ACTIONS` to
`apps.case_attachments.views.requester`; `/casework/staff/` dispatches `STAFF_ACTIONS`
to `views.staff`. Entry requester form has action `attachments`; staff entry has
action `attachment_list` and the already-authorized `case_ref`. Service interfaces:
`upload`, `requester_list/read`, `staff_list/read`. Metadata includes `evidence_version`;
binary bytes are returned only by authorized reads.

Allowed: UTF-8 plain text, 1–65536 bytes, Latin safe filename ending `.txt`, 32 files
per case. Empty text, invalid UTF-8, binary controls, wrong media type/filename,
oversized files, duplicate fields, extra files and stale proofs are rejected.
Files never create or approve an answer.

## Verification

```sh
.local/venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin .local/runtime/pg17/usr/lib/postgresql/17/bin --major 17 \
  --settings apps.case_attachments.settings -- \
  .local/venv/bin/python manage.py test apps.case_attachments.tests --noinput
```

Tests exercise actual HTTP multipart upload, exact download, escaped preview,
staff visibility and another requester's rejection, evidence and approval
invalidation, default gate, revoked capabilities, role/scope isolation, file
limits, pending clarification, CSRF, stale/cross-session forms, concurrency,
rollback and PostgreSQL immutability.

## Deliberate limits

Private BinaryField storage is a bounded synthetic prototype. Decision D-031's
separate original Object Storage is NOT_IMPLEMENTED. Production storage, scanning,
PDF/image/audio/video, real personal data, identity policy and deployment remain
out of scope. No full attachment/U03 acceptance. Organizer permissions stay closed.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.
NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.
