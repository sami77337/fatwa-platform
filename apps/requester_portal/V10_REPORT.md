# V10 lane B receipt

Base PR #228 head `12840d54c263e63b214ce72eff1d8b4f93f9900e` verified against GitHub
metadata and remote before branching. Branch `codex/20261117-v10-requester`; V9
research branch preserved. All changes are new files under `apps/requester_portal/`.
No shared source/media/casework/config/templates or AGENTS.md changes. No sub-PR.

Reviewed root rules, existing scope/decisions, V9 campaign/testing instructions,
requester/recovery/attachment/media/citation/composite service contracts.
AGENTS and scope trace remain unchanged from the previously read versions;
`.agents/skills` is absent. Current delegated lane/branch instruction governs.

Delivered: one native RTL portal, source-only approved citations, authenticated
file/audio previews, case-bound followup/upload forms, independent approval/private
availability/delivery labels and actual counts. Privacy includes draft/audit/note
exclusion, stale-answer denial, token and approving-identity revocation, cross-case
file denial, and no reading inference or new sending path. See README for exact
view/profile/URL/service contracts.

## Executed on Python 3.13.5 / fresh owned PostgreSQL 17.11

- Initial new service/form group: **10/13 PASS**, one failure and two errors.
- Corrected affected group: **4/4 PASS** (three initial failures plus the adjacent
  partial-failure projection). The other successful tests were not rerun.
- Additional integration-boundary tests: **2/2 PASS** — existing text-only path
  still requires complete signed delivery, and a revision change during aggregate
  composition refuses the snapshot. Total module contains **15 distinct tests**;
  the groups overlap and are not a new 16-test single run.
- **1/1 browser PASS**, Chromium154.0.8037.57, PG17, 5.411s; explicit local
  `sandbox=False`. Actual PNG upload/decode16×12, clarification/reply, draft hidden,
  approved-but-unavailable, private release, source/edition/page, actual WAV playback
  duration0.1s and exact file bytes, provider acceptance distinct from signed3/3,
  followup hiding the answer and stale file404, revoked capability closure.
  RTL320/1280, keyboard submissions, zero external HTTP requests/page errors.
- PASS system check, database-backed migration drift (`No changes detected`),
  Ruff/format and whitespace checks. No migrations are added.
- NOT_RUN locally: PG18, sandboxed Chrome, full V10 connected campaign or remote CI;
  these remain the integration owner's final-head checks.

Failures preserved: accepted composite parts also carry a V9 human-action flag;
initial state priority masked acceptance as unresolved. Fixed priority preserves
explicit failed/unknown states and displays accepted status plus human-action
notice. Two test fixture errors used `note` instead of `text` for clarification
and tried editing an immutable grant's expiry; corrected the fixture and advanced
the test clock instead. First browser run hit CSP unsafe-eval in a polling helper;
removed that helper and asserted actual playback without relaxing CSP. No known
remaining local failure. Prior V9 evidence was not changed.

No production, real data/accounts, external sends, U03 grants, AI rulings or
completion-percentage reassessment. Source622 remains catalog metadata.
**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
