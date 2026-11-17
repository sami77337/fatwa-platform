# Private synthetic case attachments

Requester uploads a small fabricated text, PDF, JPEG, PNG, WebP, MP3, M4A or
WAV file from the existing private case session. The original bytes, SHA-256, byte count, validated text media type,
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

Allowed: UTF-8 plain text up to 65536 bytes; PDF, JPEG, PNG, WebP, MP3, M4A and WAV
up to 192000 bytes; Latin safe filenames; 32 files per case. Empty/binary text,
wrong MIME/extension/content, invalid/truncated containers, oversized images,
animated WebP, active/encrypted PDF, excessive pages/duration, duplicate fields,
extra files and stale proofs are rejected. Files never create/approve an answer.

Validation is shared with answer media through `apps.private_media.validation`;
attachments and answer parts remain distinct domain records. Parser metadata is
stored immutably. Preview uses authorized GET on
`/casework/status/attachments/<uuid>/` or `/casework/staff/attachments/<uuid>/`.
These paths require parent URL/guard registration. Every fetch checks current
capability/staff scope; UUID alone grants nothing. No token appears in URLs.
Images/audio use native browser controls; PDF uses a sandboxed iframe and a
scriptless sandboxed media response. Existing POST download preserves original
bytes. No public/static path is created.

Migration 0003 keeps existing text originals and adds media fields/constraints.
Populated text rollback/reapply is tested. Once non-text files exist, rolling back
to text-only constraints must be blocked by PostgreSQL, preserving originals;
there is no automatic deletion or downgrade of accepted media.

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
separate original Object Storage is NOT_IMPLEMENTED. Production storage, malware scanning,
video, real personal data, identity policy and deployment remain
out of scope. No full attachment/U03 acceptance. Organizer permissions stay closed.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.
NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.
