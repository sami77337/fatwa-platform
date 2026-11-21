# Restricted citation-candidate gateway

Development only, default off. `NOT_DEPLOYED / GATES_HOLD`.

This is the first bounded internal AI task, `CITATION_CANDIDATES`. It is **not a
complete Luna implementation or evidence of scholarly quality**. No real model,
credentials, network adapter, external corpus, paid call or production activation
is included. The only supplied adapter is explicitly synthetic test support.

## Requirement trace and scope

The source decisions are in `docs/product/v12_scope_evidence/decisions.json`:
D020 preserves human originals and prohibits AI answers; D046 requires a
restricted central gateway; D068 defines V1 inline scholarly citation assistance
as derived feature `FEAT-V1-AI-CITATION-001`. D064's external ChatGPT integration
remains V2. This module does not create a new owner row or silently move V2 work.

The existing V14 owner matrix and V12 specifications map this slice as follows:

| Original owner/specification | Implemented boundary |
| --- | --- |
| 208–209 / `SPEC-U14-024` | One registered task; any other task is denied. |
| 211 / `SPEC-U14-027` | Attempt pins provider, explicit model identity, independent model version, adapter, task, prompt and schema versions. |
| 212 / `SPEC-U14-024` | Candidate locations are separate derivatives; human originals are untouched. |
| 213 / `SPEC-U14-027` | Global, task and provider kill switches apply before/after execution and on reads/selections. |
| 214, 429 / `SPEC-U14-027`, `SPEC-U15-013` | Missing provider, failed provider and rejected output have real states; manual composer remains usable. |
| 198–207, 210 / D020, D046 | No answer/draft/completion, approval, publish, delivery, identity or permission capability. |
| 555 and D068 / `SPEC-U06-009`, `SPEC-U06-024`, `SPEC-U06-025` | Existing source/version/range only; opening and selecting do not save a citation or establish scholarly correctness. |

This slice supports literal TEXT windows in an existing permitted UTF-8 library
text file or approved human answer. A human chooses the existing source and a
window of at most 4,000 characters in an original of at most 16,000 characters.
The explicit query fragment is at most 240 characters. The provider receives
that fragment, one immutable source window, source/version pins and fixed task
instructions. It receives no case/requester identity, original question, browser
request, permissions object, file handles or full unsaved answer.

Returned JSON has exactly `candidates`, containing zero to five distinct objects
with exactly `source_id`, `start`, `end`. Every range must lie in the supplied
window and be at most 1,000 characters. The source identifier must equal the
existing selected version. No generated quotation, reason, confidence claim,
URL, page, hadith number, ruling, action or tool-call field is accepted. Duplicate
JSON keys, non-finite numbers, booleans masquerading as offsets, invented IDs,
out-of-range values, duplicate entries and oversized output are rejected.
Displayed snippets are sliced afresh from the exact authorized original.

Automatic corpus retrieval/reranking, PDF/page/time candidates, verified scholarly
datasets, scientific quality evaluation, other Luna tasks and a real transport
adapter remain outside this slice. The schema can prove an existing position; it
cannot prove that a cited text supports a proposition. Human review remains
mandatory. Synthetic examples do not close that quality requirement.

## Authorization and provider contract

`GatewayAuthority.permits` is independent of citation/library authorities.
`USE` grants access to this task in the current case. **`PROCESS_CONTEXT` is a
separate explicit grant** for each draft-fragment digest and exact source version,
destination provider and model, actor/epoch/case and task. READ and CITE never
imply permission to send data to a provider. All ordinary source READ/CITE and
current human editor checks continue to apply.

Authorities expose a pure atomic non-reused `projection_epoch` including grant
changes and expiry. An operation captures exact identity, authority, source and
configuration snapshots. A short initial transaction admits an attempt and reads
the authorized bounded context. Provider execution runs outside database locks.
A fresh short transaction repeats current permissions and pins before saving
any candidate. Provider/task changes, source/identity changes and revocations
cancel candidate persistence. Final pure AI checks run **after** the existing
citation/library boundary's last callbacks, still inside the outer transaction.
Rendering and human selection stay within the same current read boundary.

`CitationProvider` is an explicit trusted adapter interface with a `ProviderSpec`
and `generate(CitationRequest) -> bytes`. `ProviderSpec.model_id` and
`model_version` are separate required identifiers, included in the processing
grant, request/context digests, immutable run seal and fresh read checks. The
synthetic fixture is explicitly `synthetic-citation-model`; no real model is
selected or backfilled. An unconfigured provider has blank model identity/version
and an explicit unavailable outcome. The frozen request contains only data;
the gateway never invokes a mutating core service on behalf of output. There is
no string-based import/plugin execution or model-controlled tool dispatcher.
Adapters must enforce the supplied monotonic deadline and bounded return. The
controller waits at most 20 seconds for a provider result. There is exactly one
daemon-worker slot per process, independent of provider identity. A timed-out
worker retains that slot until it actually exits; later requests fail quickly
without spawning more workers. Late output is discarded and has no persistence
callback or route to a retry. The gateway does **not** claim to kill a blocking
Python thread. A future real adapter
must implement transport timeouts, approved model/version configuration, actual
processing permissions and independently verified operational/quality policy.

The native panel uses a request-bound `SessionDirectory`: it rechecks the signed
staff cookie, CSRF/browser binding, identity epoch and cookie deadline on fresh
identity resolution after provider return. Its pure projection and final identity
deadline also include the exact browser session expiry, even when the directory's
underlying human identity remains valid for longer. It does not alter the shared
authentication implementation or introduce a new authentication policy.

The gateway accepts at most 8,192 output bytes. It never stores rejected raw
output, provider exception text, query text or source text in AI tables. An
idempotency key is bound to the full request/actor/case/window and cannot change
its query or actor. A repeated completed request does not call the provider again.
An interrupted attempt without a terminal outcome fails closed as incomplete;
it is not silently retried.

## Storage and failure states

`GatewayRun` is an immutable attempt with versions, identity, request/context
digests, current case versions and exact source pins. `GatewayOutcome` is an
immutable terminal audit: `SUCCEEDED`, `PROVIDER_UNAVAILABLE`, `PROVIDER_FAILED`,
`OUTPUT_REJECTED`, or `REVOKED`. `CandidateBatch` is a separate sealed derivative
containing only validated identifiers/ranges. No AI table owns original bytes or
becomes an `AnswerRevision` or `CitationSet`.

Database triggers reject history mutation, invalid seals, unregistered tasks,
malformed windows, nonexistent source identities and unbounded candidate shapes.
A revoked attempt can receive only a fixed terminal audit status; its provider
output is discarded. Reads reauthorize current grants, provider/model configuration
and exact sources. Restoring database rows does not restore a permission grant or
activate a provider. Derivatives are structurally separate, but this slice does
not introduce a deletion/rebuild workflow or claim to reproduce model output.

## Native panel and integration wiring

The panel is a sibling of the existing precise-citation composer. Its JavaScript
submits only its own bounded form. It never reads, serializes, changes or submits
the answer textarea. Result/open/failure updates replace only the result region.
Denied responses remove previous source text and keep the draft/form intact.

Opening a candidate displays the freshly authorized original with the exact
range marked. After an explicit human click and a fresh server authorization,
the panel fills only the existing source/range controls. It does **not** click
Add/Save, insert a quote, create a citation, approve or publish. The human still
selects the precise phrase occurrence and uses the existing manual citation path.
Templates escape source HTML/instructions; source/model content is never code.

Root/integrator owns these shared changes; this worktree changes only this app:

1. Register `apps.ai_gateway` in the synthetic campaign `INSTALLED_APPS`; keep:

   ```python
   FATWA_AI_GATEWAY_ENABLED = False
   FATWA_AI_CITATION_CANDIDATES_ENABLED = False
   FATWA_AI_GATEWAY_AUTHORITY = None
   FATWA_AI_CITATION_PROVIDER = None
   FATWA_AI_DISABLED_PROVIDERS = frozenset()
   ```

2. Include `apps.ai_gateway.urls` under `casework/ai-citations/`.
3. Add these exact `CaseworkGuard.ROUTES` entries, preserving all existing host,
   loopback, request budget, private response and maintenance checks:

   ```python
   "/casework/ai-citations/": ("POST",),
   "/casework/ai-citations/panel.mjs": ("GET", "HEAD"),
   ```

4. In `apps.precise_citations.editor.page`, use
   `apps.ai_gateway.panel.render_composer(request, template, context)` instead of
   its `render(request, "precise_citations/editor.html", context)` call. All
   surrounding precise source/identity transaction boundaries remain in place.
   With the gateway off, the hook returns the original template unchanged.
   With it on, a separate template inherits that composer and adds the panel.
   The hook supplies same-origin script/connect CSP; private/no-store stays in
   force. No staff action dispatcher additions or new answer save endpoint exist.

`apps.ai_gateway.settings` is an isolated default-off test profile. HTTP tests
explicitly apply these exact route/render hooks through their fixture, retaining
the real middleware; they do not certify missing campaign wiring. The protected
browser test uses **actual campaign wiring** and has no UI/render/guard patch.

## Test and evidence contract

Service/HTTP/recovery classes:

- `apps.ai_gateway.tests.CitationGatewayTests`
- `apps.ai_gateway.test_http.CitationGatewayHTTPTests`
- `apps.ai_gateway.test_recovery.CitationGatewayRecoveryTests`

The failure-first PG17 log was captured before a service implementation existed:
`ai-citation-failure-first-pg17.log` in the surrounding recovery workspace.
Run the three classes under the owned PostgreSQL 17 and 18 runner with settings
`apps.ai_gateway.settings`, or the wired campaign profile. The tests include
independent grants, source preservation, actual failure states, malformed/adversarial
output, revocation after provider return and during the final source/render
callback, idempotency, raw SQL invariants and restoration with fresh authority.

One protected native browser method:

`apps.ai_gateway.browser_tests.CitationGatewayBrowserTests.test_native_candidates_original_human_handoff_failure_revocation_and_manual_citation`

It requires `FATWA_BROWSER_SANDBOX=1`, launches with `chromium_sandbox=True`, uses
the actual campaign editor, keyboard form actions and 320/1280 RTL layouts. It
proves original opening, unchanged unsaved answer, provider payload exclusion,
explicit human handoff, missing/failed/rejected provider states, current revocation
and final saving **only through the existing human citation path**. All browser
requests stay on the owned loopback server. There is no fallback to a disabled
sandbox. A blocked Chromium launch is not browser acceptance.

Proof artifact:
`.local/qa/functional-continuation/ai-citation-browser/result.json`, with
`status=PASS`, `sandbox=true`, `provider_mode=SYNTHETIC`,
`real_provider_quality=NOT_EVALUATED`, widths `[320,1280]`, and empty
`page_errors`/`external_requests`. Screenshots and native trace share that directory.

Recovery helper: `apps.ai_gateway.recovery_support`.

- Tables: `ai_gateway_gatewayrun`, `ai_gateway_gatewayoutcome`,
  `ai_gateway_candidatebatch` (all three seeded nonempty).
- Function: `ai_gateway_history_guard()`.
- Triggers: `ai_gateway_run_guard`, `ai_gateway_outcome_guard`,
  `ai_gateway_batch_guard`.
- Twelve explicit denials: `gateway_disabled`, `task_disabled`,
  `missing_gateway_authority`, `missing_identity_directory`, `missing_provider`,
  `killed_provider`, `revoked_source_processing`, `revoked_fragment_processing`,
  `revoked_source_read`, `revoked_source_cite`, `revoked_case_scope`, `cross_actor`.

The helper validates exact restored table digests, successful and failed attempts,
original bytes, no provider replay, all twelve denials and a positive read after
current authority is restored. It returns `positive_reads_after_denial=true` and
`real_provider_quality=NOT_EVALUATED`.

### Observed local verification

The final service/HTTP/recovery run executed **25 tests successfully** on
PostgreSQL 17.11 (33.349 seconds) and 18.7 (33.876 seconds), using fresh owned
synthetic clusters. Logs: `ai-citation-model-final-pg17.log` and
`ai-citation-model-final-pg18.log` in the surrounding recovery workspace. Ruff
check/format and JavaScript syntax validation also passed.

Independent review identified two concrete gaps in the first checkpoint:
post-return elapsed-time checking did not bound an uncooperative adapter, and the
shared request directory did not retain the shorter browser-session deadline.
The regression tests were run first and failed on both behaviors
(`ai-citation-hardening-before-pg17.log`). They now prove bounded waiting, one
occupied slot, discarded late output, no late delivery after revocation, and
expiry rejection despite a still-current directory identity/epoch.

An additional failing test exposed the missing explicit model identity before it
was added to this new, undeployed app's initial schema and SQL guard. The current
test checks the independent identity/version seal, same-version/different-model
denial and SQL rejection of a configured run with a blank model identity.

`test_forbidden_task_names_and_action_outputs_preserve_all_available_core_records`
creates an actual human answer, precise citations, independent citation review and
human approval first. It snapshots every available model in casework, precise
citations, identity registry, publication/public-media/schedules/destinations and
delivery apps, plus the trusted directory's actual identities. Eleven prohibited
task names and eleven answer/approval/publication/delivery/identity/permission/tool
output fields are executed as denials. A permitted candidate request is also
executed. All snapshots remain identical, including the nonempty immutable source,
answer, approval and citation records; only AI audit/derivative tables change.

The protected browser was attempted separately. Chromium was blocked before any
page opened by the container's `socket() failed: Operation not permitted` and
`ptrace: Operation not permitted` restrictions. The failure is retained in
`ai-citation-browser-pg17.log`; no browser PASS or quality acceptance is claimed.
The actual campaign integration and hosted protected browser proof remain gates
for the integrator before counting this unit as an accepted native journey.

### Current classification at the processing boundary

When the classification ledger applies, the owner case, the selected source case
and the exact `LIBRARY_VERSION` or `ANSWER` require separate `READ` and `AI` grants
before source text enters a `SourceWindow`. Existing case/source read, citation and
gateway processing grants remain required independently. No class label grants
permission by itself. Unknown sources fail closed; a saved label cannot be
bypassed by disabling classification enforcement.

The two short authorization stages retain their classification/source digests
and the configured privacy authority's identity and pure generation. A change
during the provider call rejects its result and leaves only the existing
`REVOKED` run audit; there is no candidate batch or late handoff. Opening or
selecting a previously saved batch repeats current classification authorization.
Only the exact native `SessionDirectory` wrapping the configured directory is
accepted; subclasses and alternate directories acquire no additional trust.

The provider still runs outside a database transaction. Composition uses
`PrivacyResponses` with its response-wide pure pins and short authorization
transactions, not an outer transaction around the external adapter. No provider,
model, network access, production permission or scholarly quality acceptance is
added by these hooks.

Regression labels: `apps.ai_gateway.privacy_tests` and
`apps.ai_gateway.privacy_http_tests`. The latter exercises the actual campaign
guard/routes/rendering with classified sources, native AI request/open/selection,
mid-provider privacy revocation, and native staff-session fresh authentication
and explicit revocation with privacy enabled. These are PostgreSQL/native HTTP
tests; they do not claim a new protected-browser acceptance run. The consumer
integration requires the privacy app, catalog, current library hooks and the
non-transactional response guard; no new tables or recovery helper are introduced.

The focused failure-first consumer run exposed 11 failed assertions out of 12
tests before these hooks (`privacy-consumers-before-configured-pg17.log`). A
separate approved-answer source regression then failed when `AI` was granted
without `READ` (`privacy-ai-answer-before-pg17.log`); both actions are now required.
The final combined service/native HTTP/recovery regression passed **131/131** on
PostgreSQL 17.11 in 124.812 seconds and PostgreSQL 18.7 in 126.964 seconds, with
fresh owned clusters and `apps.data_privacy.settings` on 2026-11-21. The set
includes 19 new classified-consumer assertions plus existing AI, data-quality
(including its review regressions), team updates, identity-registry and privacy
ledger tests. Logs are `privacy-consumers-final-pg17.log` and
`privacy-consumers-final-pg18.log` in the surrounding recovery workspace.
Ruff check/format and `git diff --check` passed. No protected-browser acceptance
or production grant is inferred from these local results.
