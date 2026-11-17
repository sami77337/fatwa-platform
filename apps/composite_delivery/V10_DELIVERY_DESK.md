# V10 F — native composite delivery control desk

Verified base: PR #228, `12840d54c263e63b214ce72eff1d8b4f93f9900e`.
Branch: `codex/20261117-v10-delivery-desk`. V9 branch/commit remain intact.
Ownership: only `apps/composite_delivery/**`; no changes to shared routes/settings,
casework, answer_media, source intake, existing engine/queue, AGENTS.md or old reports.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
No external send, production signer, production identity, real data, U03 expansion,
main merge, sub-PR or completion-percentage claim. Actual channel capabilities are
not inferred from these fixtures: all profiles are declared offline simulations.

## New usable behavior

- One Arabic RTL control screen for every canonical text/file/audio/image part:
  filename/type/size, raw content hash, part UUID, signed plan-envelope digest,
  capability reason, queue state, verified provider evidence and next human action.
- Recorded source channel/account/conversation/thread/message and destination
  identity hash are tied to the same canonical plan. These are origin references,
  not guessed live API addresses. The UI cannot edit the recipient or channel.
- Current scholarly decision, facts/answer revisions, manifest and capability
  fingerprint remain distinct from the independent signed return permission. The
  latter is reverified and its expiration displayed separately from provider proof.
- Native export and signed-permission import preserve V9's all-parts requirement.
  Every action/export checks optimistic case/evidence revisions AND the current
  plan hash inside the same case/queue transaction. Unsupported audio/file stays
  visible and blocks staging; the desk never turns the package into text-only.
- Per-part signed provider-evidence import uses an existing worker lease and the
  existing signed-event engine. The selected part, signed ordinal, plan, envelope
  digest, attempt and current case must match. Valid acceptance stays unconfirmed.
- Expired attempts can be explicitly quarantined through the existing engine.
  Later signed evidence can reconcile the matching unresolved attempt. Completed,
  failed and unresolved parts are not re-leased or silently retried.
- Aggregate partial/failure/unresolved labels and per-part next steps distinguish
  all states. Revoked/unavailable provider verifiers cannot claim delivery. A
  revoked/expired return permission does not erase historical provider receipts.
- New answers/facts, changed capabilities and unavailable/ambiguous origin close
  stale actions and parts. Missing origin asks the human to resolve it in intake;
  this desk does not decide source correlation or grant access to unresolved events.
- Native CSRF, trusted browser identity/scope/epoch, exact field allowlists,
  bounded duplicate-key-rejecting JSON, no-store responses, and no echo of receipt
  signatures/lease secrets. ORGANIZER_ADMIN remains denied.

## Coordinator integration — exact wiring

Existing V9 config already registers composite_delivery and its flags/verifiers.
There are **no new migrations or schema changes** and no new runtime dependency.

In the unified staff dispatcher, route every action in
`apps.composite_delivery.views.ACTIONS` to `apps.composite_delivery.views.desk`.
The existing `composite_open` entry button can stay as-is. Replace the V9
`apps.requester_team_journey.composite` dispatch import with this new owned view;
keep the existing parent `_panel(..., "cases")` wrapping if used. Do not run both
handlers for the same request. The five actions are:

| Action | Native fields beyond CSRF/action/case_ref |
| --- | --- |
| composite_open | none |
| composite_export | revision, evidence_version, plan_sha256 |
| composite_stage | snapshot fields above + confirm=yes, response_json |
| composite_reconcile | snapshot fields above + confirm=yes |
| composite_receipt | snapshot fields above + confirm=yes, part_id, response_json |

The view renders `composite_delivery/control.html` (unique name, no shadowing of
V9's shared desk template) and uses the existing `/casework/staff/` path, session,
styles and CSRF. `snapshot_fields.html` is an internal fragment. No new guard path,
public GET route or permission is needed. `apps.composite_delivery.urls` is an
**owned test composition** over existing campaign URLs; it proves this dispatcher
connection without editing shared files. Production/campaign settings stay with
the coordinator. Existing source-media readers/storage adapters are unchanged.

Internal APIs for a larger integrated view:

- `desk.read_delivery_desk(**common)` returns one current authorized projection;
  `common={case_id, subject_id, provider, synthetic_fixtures_only=True}`. It can
  return a safe `blocked` explanation with no old parts. Otherwise it contains
  origin, revisions, decision/plan/manifest/capability identities, permission,
  aggregate evidence and per-part state/action metadata. Never reuse cached success
  after an authorization/context failure.
- `desk.apply_desk_action(**common, action, revision, evidence_version,
  plan_sha256, response_json="", part_id="")` validates the exact snapshot under
  locks and calls existing prepare/stage/record/quarantine services. Export returns
  the original V9 prepared request; other actions return a fixed notice.
- Trusted `FATWA_CASE_DELIVERY_APPROVAL_VERIFIER` and
  `FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER` remain server configured. The desk
  neither signs nor issues leases. Worker fixture code still uses the existing
  reserve/resolve/simulator APIs outside HTTP.

Independent approval response keeps the V9 JSON shape:
`{"request_sha256": "<plan_sha256>", "receipt": <SignedApprovalReceipt fields>}`.

Provider evidence response uses the following exact offline fixture construction:

```python
from dataclasses import asdict
import json

# Existing authorized lease and resolved part; synthetic simulator only.
event = simulator.event(lease=lease, part=part, reported="DELIVERED")
bundle = json.dumps({
    "schema": "fatwa.composite-provider-evidence.v1",
    "part_id": part["id"],
    "lease": {**asdict(lease), "expires_at": lease.expires_at.isoformat()},
    "event": asdict(event),
})
```

The existing WorkerLease supplies intent_key/token/owner/expires_at. The event
contains every existing SignedProviderEvent field, including its signature.
No private
key is imported. This handoff contains an attempt token: the desk marks the input
sensitive and never echoes/persists the raw bundle. Only the engine's existing
signature/audit evidence is stored. No provider ID or destination can be changed
through the form. The matching tests demonstrate exact bundle construction.

## Verification and historical limits

Python3.13.16 / PostgreSQL17.12 / Chromium154.0.8037.57. Fresh owned clusters only.
No V6–V9 unaffected test suites were rerun.

- Initial runner invocation used a slash in the settings module and failed before
  Django started. Corrected to `apps.composite_delivery.settings`.
- First eight-test run failed in fixture setup: calling another TestCase's super()
  with an unrelated instance. Replaced with a proper shared fixture setup; no
  product workaround. Ruff caught a missing test import, fixed before execution.
- Next run: **7/8 PASS**, one failed HTML assertion expected a capability warning
  twice although both reason/action labels rendered it (four occurrences). The
  test now checks the actual two unsupported parts and warning presence.
- Corrected test + first real browser: **2/2 PASS**, 8.362s. No product failures.
- Added aggregate Arabic state labels and a named JSON-constant rejection helper:
  **3/3 affected HTTP tests PASS**, 3.422s (export/stage/receipts, timeout and JSON).
- After visual review corrected bidi/date formatting, final browser rerun:
  **1/1 PASS**, 7.678s. Keyboard form submission; RTL 320/1280; zero horizontal
  overflow, external requests or page errors. Local `sandbox=False` explicitly;
  sandboxed browser is for campaign CI, not claimed here.
- Additional focused cross-case bundle relabelling + ORGANIZER_ADMIN denial test:
  **PASS**. Across runs, all **9 distinct HTTP/PostgreSQL tests +1 browser** pass;
  overlapping runs are not additive evidence or a completion percentage.
- PostgreSQL migrations/bootstrap, Django system check, migration drift, Ruff,
  format and diff checks pass. No schema change. PG18 and full integrated campaign
  journey are **NOT RUN here**, reserved for the coordinator's final verification.

Browser journey: offline Telegram source + bound attachment → already human-approved
text/file/audio → native download of exact plan → independently signed permission
import → text ACCEPTED then signed DELIVERED → file FAILED → audio expired/unknown
then signed reconciliation → two verified parts and one failure, exactly three
attempts and three intents → new answer revision hides all old delivery parts.
Snapshots/results are generated in `.local/qa/v10-delivery-desk/` by the test.

Reproduce only when changed or for final integrated verification:

```sh
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.composite_delivery.settings -- \
  .venv/bin/python manage.py test apps.composite_delivery.test_desk --verbosity 2

FATWA_BROWSER_SANDBOX=1 .venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.composite_delivery.settings -- \
  .venv/bin/python manage.py test apps.composite_delivery.test_browser --verbosity 2
```

Browser harness uses Playwright1.58.0 installed only in the local test environment
and the configured Chromium executable; shared dependency files were not edited.
Existing eight-part/parser/storage bounds, private-release policy, external
connector restrictions and all acceptance gates remain unchanged.
