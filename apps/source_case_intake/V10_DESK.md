# V10 source intake desk — integration handoff

Base: PR #228, `12840d54c263e63b214ce72eff1d8b4f93f9900e`, verified via GitHub
and remote before branching `codex/20261117-v10-origin-desk`. V9 work remains on
its old branch. Ownership: `apps/source_case_intake/**` only. No new migration,
provider, public endpoint, grant or shared-file modification.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.** Only synthetic
owned development databases and the existing explicitly scoped MUFTI role. U03
organizer roles stay denied. This does not update the owner's 69% reference estimate.
AGENTS.md and the scope/decisions read for V9 remain applicable; the current V9
campaign test and integration contract were reviewed. `.agents/skills` is absent.

## What is now usable

- Native Arabic forms show authorized stored events, filter by source and state,
  and paginate 25 at a time. Reviewer scope sees unbound receipts; bound receipts
  require their actual case scope, even for a queue reviewer.
- Event detail shows the unchanged question and sender identity, source account,
  conversation/thread/message/reply positions and raw digest. The raw preview is
  escaped text (hexadecimal for invalid UTF-8); a separate attachment download
  returns the exact stored bytes. No public URL, raw HTML rendering or credential
  in query strings is introduced.
- The reviewer can explicitly create a separate case or append to an offered
  same-origin case, with a note and confirmation. Followup requires the current
  requester capability as well as MUFTI case scope. Source conflict/edit holds
  cannot be overridden. Signed browser-bound forms expire after 15 minutes;
  changed case/evidence versions, repeat decisions and changed authority fail.
- Pending capture can resume the existing deterministic processing pipeline from
  the desk. It cannot bypass unresolved-review status or create duplicates.
- Declared synthetic source files can be uploaded through the existing V8/V9
  service with current case versions and staff authority checked after parsing
  and before commit. V9 external-storage bindings are preserved. No file fetch
  from a provider is implied.
- The timeline reads canonical CaseEvidence in version order and shows source
  receipts, followups and attachments, their file-source IDs, hashes and authorized
  private file links. It does not copy facts or mistake provider time for local
  evidence order.

New case creation **does not grant staff scope** or display the new requester
capability in the desk. A human decision's result reference is shown; opening the
new case requires the existing explicit scope/recovery workflow. The directory
must be configured by the trusted synthetic harness, not modified by a browser.

## Dispatcher and profile contract

Register `apps.source_case_intake` as already done in V9. Keep both flags false by
default, enabling them explicitly only in the synthetic campaign/demo:

```python
FATWA_SOURCE_CASE_INTAKE_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = False
```

The shared `/casework/staff/` POST dispatcher can use:

```python
from apps.source_case_intake.views import ACTIONS, desk

if request.POST.get("action") in ACTIONS:
    return desk(request)
```

`ACTIONS` = `source_inbox`, `source_filter`, `source_open`, `source_raw`,
`source_raw_view`, `source_resolve`, `source_timeline`, `source_attach`,
`source_resume`. The navigation entry posts `action=source_inbox`. From a case,
post `action=source_timeline` plus `case_ref`. Each form includes CSRF. Do not run
capture/ingest inside a caller transaction or treat UI preference as authority.

The application-local `apps.source_case_intake.desk_settings` selects the local
`urls` overlay for independent development. It uses existing campaign URLs,
login/session, private headers, request limits, loopback guard and CSS. No new
route must be whitelisted. In this isolated profile GET staff opens the source
inbox; the combined dispatcher can keep its existing default. Files use existing
`/casework/staff/attachments/<uuid>/` authorization.

Services in `desk_services.py`: `inbox`, `detail`, `timeline`, `resume` accept
`subject_id`, trusted `provider`, and `synthetic_fixtures_only=True`.
`inbox` additionally accepts `source`, `state`, `page`. Existing `resolve_review`
and `attach_fixture` now accept optional `expected_revision` and
`expected_evidence_version`; the UI always supplies them for case mutations.
`attach_fixture` also accepts `staff_subject_id`/`staff_provider` for explicit
browser staff authority, while existing capability-only simulator calls retain
their original contract. No other app's service signature changed.

The shared routing/settings/templates are integration-owned and were not edited.
There is no assumption that this app-local screen is already wired into the
combined V10 desk until the integrator adds the dispatcher and navigation entry.

## Run the manual UI

With Python3.13 and pinned repository requirements:

```sh
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.source_case_intake.desk_settings -- \
  .venv/bin/python -m apps.source_case_intake.desk_demo
```

Open the printed loopback login. The temporary 45-minute synthetic directory is
scoped to the three fixture cases and source review queue. It prints a temporary
credential, the Telegram case capability and a tiny local TXT path. Review message
2 as a followup, split message3 from a different sender, upload the file from
message1's detail and open the timeline. Pending message4 can be resumed into
review. `--smoke` prepares/checks fixtures without serving or printing capabilities.
No answers, human scholarly approvals, grants to new split cases or deliveries
are generated by this demo.

## Focused evidence and limits

PostgreSQL17.12 / Python3.13.16 / Django5.2.18:

- 11 initial HTTP/security tests PASS, then the new pending-resume and raw-preview
  tests PASS separately: **13 distinct HTTP tests**. No unrelated passing suites
  were manually repeated.
- **4 targeted inherited service regressions PASS**: review-authority rollback,
  delayed-parent review, attachment replay/cross-case denial and attachment
  failure rollback. The full V9 suite was not rerun.
- System check, complete registered migration-drift check, Ruff lint/format,
  diff whitespace check and the standalone demo smoke all PASS. Smoke created
  three source cases, two unresolved review tickets and one pending receipt.
- **1 Chromium154.0.8037.57 journey PASS**, local explicit `sandbox=False`:
  3 source lists, unresolved queue, exact raw download, same-person followup,
  different-person split without grant, real multipart upload/private read,
  canonical evidence1–3, RTL320/1280, keyboard submit, revoked-file404,
  zero external requests and zero page errors. Artifacts:
  `.local/qa/v10-origin/browser/{result.json,timeline-320.png,timeline-1280.png}`.
- Historical browser harness failures are preserved: ORM lookup from Playwright's
  async context, then an ambiguous event1 selector shared by Telegram and website.
  DB assertions moved outside Playwright; source names were added to event buttons
  for clear labels. Both failed runs preceded the successful journey.

Run the component suite with the same helper and `manage.py test
apps.source_case_intake.http_tests`; browser module is
`apps.source_case_intake.browser_tests` (Playwright installed in the test environment).
CI/PG18/sandboxed Chrome and the complete V10 journey remain integrator-owned and
NOT_RUN here. Browser evidence precedes the additive raw-preview form; that form
has escaped-content and foreign-case HTTP tests, not a separate browser claim.

WhatsApp/Facebook/Instagram remain held; no credentials/contracts were added.
Captionless or unsupported media and conflicting source edits stay held under the
V9 contract. Unknown sender identities cannot be manually mapped into another
person. No new permission policy, malware scanner, storage limit increase,
external message, live account or production operation is provided.
