# Content and attachment reports — synthetic development workflow

This opt-in feature implements the reporting and human-review portion of owner
points **470–472**, traced to `SPEC-U09-027` and `SPEC-U15-008`. The native requester
portal can report a problem with an authorized, currently available answer or
answer part. Authorized staff can report a currently published edition or an
existing authorized transcript. The hadith-specific portion of point 471 remains
deferred; no hadith source or verification workflow is created here. Visitor
analytics in the wider U09 specification is outside this change.

## User journeys

1. A requester opens their existing capability-protected case, chooses the
   answer or an exact part, selects a reason, and describes the problem. An
   optional plain-text note identifies the problem or reproduction steps. The
   post/redirect/get receipt explicitly says that receipt is not a repair.
2. The scoped staff desk shows the immutable report, its exact version pins and
   the review history. Human review follows `OPEN → IN_REVIEW → RESOLVED` or
   `DISMISSED`. Both closure decisions require an action note and a verification
   note. A closed report can be reopened with a documented reason.
3. Staff can prepare a report from an existing published-edition or transcript
   reader. The server revalidates the target when the report is submitted; a
   withdrawn or superseded publication and a revoked transcript permission
   cannot be reported using an earlier form.
4. Repeated reports about the same exact target may be linked. Their original
   submissions, states and histories remain independent. Linking neither merges
   nor deletes a report, and a reversed duplicate link is rejected.

Reporting, review, closure and linking do not create a new answer, revise a
publication, rewrite a transcript, append requester evidence, send a message, or
claim that a scholarly statement is correct. A substantive correction remains a
separate action by the appropriately authorized human.

## Authorization, versioning and privacy

- `FATWA_CONTENT_REPORTS_ENABLED` defaults to false. The implementation also
  requires `FATWA_PRODUCTION=0`, the existing owned PostgreSQL synthetic database,
  and explicit `synthetic_fixtures_only=True`.
- Requester selection comes from the actual current portal reader. Approval
  alone does not release an answer. Existing signed legacy delivery or private
  multipart-release checks remain mandatory. Missing or corrupt source storage
  cannot be converted into a grant to stale content; if the reader denies the
  answer, no new target is offered. Existing minimal receipts remain visible
  with a valid current case capability.
- An answer/part report pins the case revision, approved answer, answer revision,
  evidence version, exact content digest and multipart manifest digest where
  present. Publication reports pin the current published edition, source answer
  and content digest. Transcript reports pin the existing link, evidence version
  and source digest through the research reader and its separate permissions.
- Staff require current case scope and an explicit configured
  `ContentReportAuthority` for `READ`, `SUBMIT`, `TRIAGE` or `LINK`. This seam has
  no permissive default and grants no content-editing authority. Its
  `projection_epoch()` must return an atomic, side-effect-free policy revision
  covering every reporting grant input, including expiry and changes made by
  permission callbacks. An unversioned reporting policy fails closed.
- A complete staff operation and the native HTML render share a final
  authorization boundary. It pins provider identity, current case scope and the
  reporting policy revision across all report kinds. Source preparation and
  submission additionally pin canonical case state, publication state and the
  source-rights ledger. Transcript reporting requires versioned research rights
  and a versioned `KnowledgeAuthority` for the separate `OPEN_TRANSCRIPT` grant;
  the research reader's existing source-rights adapter remains supported. Policy
  changes, expiry, source withdrawal and replacement during the final callback
  or render reject the whole result and roll back nested writes.
- Requester forms bind the capability, browser CSRF context, case reference,
  revision and idempotency key. Replaying a form after switching cases cannot
  save or echo its description into the other case. Same-case stale forms retain
  the requester's text for review but cannot create a report about a stale target.
- The requester page holds the actual portal snapshot through report enrichment
  and HTML rendering. A late release withdrawal or capability revocation cannot
  leave an earlier answer or attachment URL in the composed response.
- Submissions and triage commands have idempotency keys. Reusing a key with a
  different payload fails. Expected report versions reject concurrent stale
  decisions; the canonical case lock serializes the operations.
- Reports store version metadata and the human's own bounded notes. They do not
  copy source bytes, answer text, transcript text, storage paths or credentials.
  Requester receipts omit staff notes, actor identity, source digests and target
  identifiers. Native templates escape all descriptions and notes.
- Limits are 128 reports per case, 64 events per report, and 2,000 characters for
  each description or note, in addition to existing HTTP budgets and CSRF guards.

## Persistence and integration

`ContentReport` is an immutable initial submission. `ReportEvent` is append-only;
the current status is derived from its verified sequence. PostgreSQL triggers
reject edits/deletions, invalid target bindings, skipped lifecycle transitions,
unverified closure and links to another case or target. Failed late checks roll
back the report and any nested database writes.

The models are `content_reports.ContentReport` and `content_reports.ReportEvent`.
Migration `0002_immutable_history` depends on the existing answer-media,
publication and transcript binding migrations. The feature creates no media
files. Recovery inventory must include both tables and both triggers/functions;
the shared recovery composition is maintained by the integrating lane.

Native staff actions, exported by `views.ACTIONS`, are `reports_open`,
`report_prepare`, `report_submit`, and `report_advance`. They use the existing
`/casework/staff/` endpoint. Entry from a case posts `reports_open` plus
`case_ref`; entry from a source posts `report_prepare`, `case_ref`, `target_kind`
(`PUBLICATION` or `TRANSCRIPT`) and `target_id`. The requester form is composed on
the existing `/casework/status/` route only when the feature is enabled.

## Observed local verification

The implementation was exercised on the current integration working tree with
Python 3.13.5, pinned dependencies, fresh owned PostgreSQL 17.11 and PostgreSQL
18.7 clusters, and `config.settings.campaign_review`:

| Suite | PG17 | PG18 |
| --- | --- | --- |
| Initial 18 report service/native HTTP contracts plus 25 existing requester portal/workflow contracts | 43 passed, 20.697 s | 43 passed, 21.013 s |
| Final report contracts plus seven independent staff authorization regressions | 25 passed, 14.091 s | Included in final combined run |
| Final combined report, staff authorization, four requester composition regressions and existing portal/workflow contracts | Verified in focused runs; no single combined PG17 result claimed | 54 passed, 32.014 s |

These tests cover requester submission through the actual campaign dispatcher,
staff publication/transcript native forms, verified closure, source/case
immutability, report replay and concurrent replay, stale versions, default deny,
permission revocation, capability switching, CSRF, escaped notes and transactional
rollback after a late followup or revocation. Report-only replay and lifecycle
tests include explicit stale-command and duplicate-link rejection.

Independent review reproduced late authorization defects in composed pages and
mixed-kind/source reporting. The tracked regression modules are
`apps.content_reports.test_review` and
`apps.content_reports.test_requester_review`. They exercise revocation of an
earlier report kind by the last permission callback, research and knowledge
permission changes after the last transcript read, publication withdrawal,
unversioned-policy denial, and policy/release/capability changes during native
HTML rendering. All are included in the final PostgreSQL 18 run above. The four
requester composition regressions and 25 existing portal/workflow contracts also
passed a focused PostgreSQL 17 run by the independent reviewer.

The first local report run exposed a nested queue ownership-preflight ordering
error. The code was corrected to use the existing outer delivery/queue boundary;
no guard was relaxed. The final results above supersede that failed local run.
Ruff check and formatting passed. A protected browser was not available in this
executor: Chromium failed before UI at an operating-system socket permission
boundary. No browser acceptance pass is claimed from these HTTP tests.

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/pg17/bin --major 17 \
  --settings config.settings.campaign_review -- python manage.py test \
  apps.content_reports.tests apps.content_reports.test_review \
  apps.content_reports.test_requester_review apps.requester_portal.tests \
  apps.requester_portal.workflow_tests --noinput
```

**NOT_DEPLOYED / GATES_HOLD.** No acceptance status, pending policy or production
permission is promoted by this implementation or its local evidence.
