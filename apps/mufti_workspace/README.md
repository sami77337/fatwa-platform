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
