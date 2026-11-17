# V11 lane B — functional completion receipt

Verified PR #229 and remote `codex/20261117-v10-integration` at
`0f90bb4f6c4ba426055fc77a3a783c2061d6ee19` before creating
`codex/20261117-v11-requester`. V10 branch preserved; no main checkout or merge.
Read AGENTS, scope trace, current decision log and V10 contracts/testing receipt;
`.agents/skills` is absent. Ownership remains `apps/requester_portal/**` only.

## Product gaps closed

- Clarification reply plus optional attachment is one native submission, backed
  by existing canonical services with all-or-nothing evidence changes. Tested with
  actual private filesystem storage and read through the existing Mufti workspace.
- Clear next action, text/file chronology and a one-time browser-bound save notice
  remove the need to infer whether a response or file was saved.
- Transient snapshot/storage failure has a private empty retry screen and preserves
  valid access. Revoked access still closes; no stale answer fallback or read claim.
- Text-only native submissions, stale forms, missing file consent, oversized files,
  cross-case forms and notice replay keep their explicit privacy/failure behavior.

## Local evidence — Python3.13.5 / isolated PostgreSQL17.11

- Initial focused run: **10/15 PASS**, two failures and three errors from composing
  nested canonical mutations without the queue's authorized transaction context.
- An initial targeted edit missed the formatted context-manager line; the 7-test
  targeted run still failed six, while the updated malformed-input case passed.
  A stronger storage-failure assertion correctly exposed that storage had not yet
  been reached. No guard was relaxed.
- Corrected transaction composition: **6/6 affected cases PASS**. Filesystem write
  failure is actually injected and asserted, and text/evidence/clarification roll
  back. Same-case Mufti reads see exact reply/file bytes after success.
- Native optional-file regression: **1/1 PASS**, added after actual Chrome exposed
  an empty file control as a POST field. Only the exact empty representation is
  accepted; fabricated file text remains rejected.
- These groups cover **16 distinct service/HTTP scenarios** (10 new workflow tests
  and six affected V10 form tests). Counts overlap; no claim of a single new
  16-test full run, and unrelated successful suites were not rerun.
- **Chrome154.0.8037.57 1/1 PASS**, PG17,5.466s, explicit local sandbox=False.
  One-step reply+file, saved notice and merged timeline; actual image16×12/audio0.1s,
  authorized citations, independent private release, provider acceptance versus
  signed3/3, new facts hiding the old answer/file404, revoked capability closure,
  RTL320/1280 and keyboard, zero external requests/page errors.
  The initial browser attempt reached the final text-only reply then failed400 on
  the native empty file field; after the fix the full affected journey passed.
- PASS system checks, database-backed migration drift (no changes), Ruff/format
  and diff checks. No migrations or shared configuration changes were added.
- NOT_RUN: local PG18/sandboxed Chrome and final V11 aggregate/remote CI. Integrator
  owns exact-head combined validation. Historical V9/V10 evidence is unchanged.

## Handoff / remaining boundaries

Existing V10 portal registration suffices. New service/action contracts are in
README; Mufti handoff is the canonical case/evidence and existing attachment
services, not a notification, new permission or parallel task record. Add
`apps.requester_portal.workflow_tests` to V11 CI. Browser artifacts are under
`.local/qa/v11-requester/browser/` (no raw capabilities or private backups).

One optional file per reply; existing format/size/parser limits remain. There is
no malware scanner. A failed database transaction can leave an unbound immutable
blob for the existing safe GC policy; no automatic guessed deletion. No autosaved
private drafts, notifications, external provider connection or new recovery policy.
If the current snapshot itself cannot be read after failure, the private retry
screen intentionally withholds both the snapshot and submitted text; check saved
history before retrying. The signed save notice is temporary and not an audit log.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.** Synthetic only;
no U03 grants, AI rulings, real data, external send, production or sub-PR. Owner's
74% ±8 reference is not reassessed; this is not acceptance or pilot authorization.
