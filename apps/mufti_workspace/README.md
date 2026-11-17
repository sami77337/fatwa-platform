# Connected Mufti case workspace

An opt-in RTL presentation of the existing canonical case. No models, writes,
permission grants, delivery engine or parallel case records are added.

The selected-case screen shows the current case reference, record/evidence/answer
versions, original question, followups, source origins, attachment metadata and
scoped preview/download links. It includes actual existing clarification, draft,
return and approval forms; full answer parts are shown through the existing
verified manifest projection before whole-answer approval. A stale save retains
its rejected text separately, refreshes current facts and preserves old revisions.
Existing trusted access-recovery actions remain available under their existing gate.

The shared header keeps the same case when opening attachments, citations,
answer parts/private availability, composite delivery and independent experimental
publication. It posts existing exact action/case_ref forms. `case_workspace` is
the explicit overview action, avoiding the legacy delivery panel's `open` action.
No case cookie or GET selector grants authority. Unknown/future action semantics
are not inferred; the campaign integrator can update navigation to its reviewed
composer/delivery actions.

## Integration hooks

Register `apps.mufti_workspace` in the synthetic campaign and append context
processor `apps.mufti_workspace.context.case_workspace`. Define
`FATWA_MUFTI_WORKSPACE_ENABLED=False` by default; explicitly enable only the closed
synthetic demo. The parent foundation changes already provide:

- `read_workspace_case(include_answer_manifest=False)` for a metadata-only context
  read; normal review views retain the existing default full manifest verification.
- Global `casework/base.html` includes `mufti_workspace/header.html` and `aside.html`
  only when the context exists, with responsive `mufti-layout` CSS.
- Team `_page` selects `mufti_workspace/overview.html` for a selected case with the
  flag on; the scoped `case_workspace` action opens it and resets the panel cookie.
- The attachment desk extends the same base, preserving its native forms.

No other app, global template, setting or mutation API is owned by this slice.
`apps.mufti_workspace.settings` is a focused test composition for these hooks.

## Trust and freshness

The processor is eligible only for POST `/casework/staff/` with a single valid
case_ref and action. Feature-off, GET, requester paths and non-case panels produce
no context. An eligible call authenticates the current scoped MUFTI cookie, uses
RequestDirectory, resolves only that authorized reference and rereads the canonical
workspace. Metadata is read under the same core case/identity/integrity boundary
with matching revision pins. A final identity check catches revocation during
projection. Eligible authorization/integrity failures **propagate** to the existing
handler's denial response; they never silently leave prior private content visible.

Attachment queries select metadata fields only. The processor never opens an
original file, runs a parser, issues a send or attempts delivery verification.
Actual previews remain separately authenticated file requests. Original source
labels derive from the authorized ORIGINAL evidence origin; without one the UI
explicitly names the stored intake channel. A stored approval is labeled as such.
Availability and delivery require their existing panels' fresh checks: row presence
is never presented as verified access, delivery or requester reading.

## Focused verification

```sh
/workspace/fatwa-platform/.local/venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /workspace/fatwa-platform/.local/runtime/pg17/usr/lib/postgresql/17/bin \
  --major 17 --settings apps.mufti_workspace.settings -- \
  /workspace/fatwa-platform/.local/venv/bin/python manage.py test apps.mufti_workspace.tests --noinput
```

Tests exercise native edit/return/revise/approve, clarification and requester
followup, stale write preservation, default closure, no requester/GET/cookie
selection, foreign scope and non-MUFTI denial, mid-render revocation, concurrent
facts, media metadata without original I/O, same-case panel navigation, delivery
cookie recovery, CSRF/duplicate fields and source labeling. Browser integration
is a separate campaign test; no browser pass is inferred from these HTTP checks.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED. No production deployment, external
send, real data, AI ruling or inferred U03 acceptance.

## V11 actionable current-case workflow

`workflow.describe_work` adds a next-step card, procedural review blockers and a
four-stage record summary to the existing frame. It derives missing answer,
pending clarification, outdated evidence and required revision from the canonical
snapshot. The current return reason is read from the existing decision; the
changes panel shows only evidence versions newer than the latest answer's basis.
There is no completion percentage or inference that viewing a fact means reviewing it.

The primary button navigates to the existing case/editor/review or media/delivery
panel with the same case reference. It never submits approval, release or sending.
Optional tools are offered only when their existing tab flag is on. An approval
still requires the native review form and its current revision/evidence checks.

A matching `PrivateAnswerRelease` is read as metadata under the canonical case
lock, matching current answer, decision, evidence and manifest digest. Its state
is `RECORDED_NOT_VERIFIED`, never an assertion of current access, rights, delivery
or reading. Closed private-release settings remain visibly closed. A newer answer
cannot inherit the old release. Text-only availability retains its existing path
and is explicitly not checked by this summary. No original media bytes, parsers,
source rights validators or delivery verifiers run in the frame.

There is no new route, flag, model or shared-template hook. The existing header
includes `next_actions.html`; selectors are `#mufti-next-actions`,
`#mufti-next-action`, `#mufti-review-blockers`, `#mufti-evidence-changes` and
`#mufti-return-reason`. Research/rights lanes may extend the existing `TABS`
registration and reviewed navigation once their contracts are integrated; this
slice invents no research action, citation requirement or rights grant.

Focused V11 verification: six added PostgreSQL/native HTTP cases plus the ten
existing workspace cases (16 passed on PostgreSQL17.12). The release test covers
separate approval/release, disabling availability, and a new revision that leaves
the old release only in history. The evidence test distinguishes previously
reviewed basis from subsequent facts without mutating either. Browser evidence is
owned by campaign integration and is not inferred from these results.
