# V11 source workflow — integration and acceptance candidate

Base verified against PR #229 and remote:
`0f90bb4f6c4ba426055fc77a3a783c2061d6ee19`. Branch:
`codex/20261117-v11-source-desk`. V10 branch preserved. Exclusive changes remain
inside `apps/source_case_intake/**`; no config/shared template/provider expansion.
AGENTS.md, prior scope/decisions and current V10 product/testing instructions
were reviewed. `.agents/skills` is absent.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.** The owner's
74% ±8 is a reference, not recalculated here. This is a testable acceptance
candidate, not owner acceptance, a live pilot, or permission to use real data.

## Functional changes since V10

1. **Generate repeatable source events in the browser.** From an existing scoped
   source receipt, the optional local simulator can generate a same-sender reply,
   a different-sender/same-name reply, an unknown-parent reply, or replay the exact
   original. It supports only the existing Telegram/YouTube/website contracts.
   Scenario and confirmation are the only user choices; raw payload, sender,
   account and source IDs cannot be submitted. A signed browser-bound nonce makes
   a repeated submit produce the same immutable receipt. No network or provider
   credentials are involved. A generated reply enters human review without
   changing canonical case evidence. It uses the case's existing sender/location
   only in this explicitly synthetic setting and never asserts external identity.
2. **Track review work without rewriting source facts.** `SourceReviewNote` stores
   immutable, sequenced NOTE/HOLD/REOPEN entries with actor, provider, epoch and
   time. A hold blocks both UI and direct `resolve_review`; explicit reopening
   with a reason is required. Reopening does not bypass a source edit/conflict or
   identity mismatch. Notes are not scholarly approval and do not alter evidence.
   At most 64 notes of 2000 characters per receipt in this bounded development lane.
3. **Find and return to work.** Search original text or exact-source identifiers,
   conversation or case reference (bounded, case-insensitive substring search;
   no semantic/fuzzy quality claim). Filters include held reviews and declared
   files still missing. Query/source/state/page survive event/raw navigation in
   a short-lived signed, HttpOnly browser preference, never an authorization grant.
   `source_return` restores the results; `source_inbox` deliberately resets them.
4. **Continue the same case.** Authorized bound forms propagate and verify
   `case_ref` for the existing Mufti workspace context. Unbound simulator results
   suppress the case frame so an unreviewed message is not shown as already part
   of that case. Timeline has a native POST back to the canonical `open` action.
   Audio/image/PDF use the existing private attachment routes in native controls;
   no public URL or duplicate file storage. Declared/missing file counts and human
   review history are visible beside the unchanged original.

## Integration contract

- Apply `source_case_intake.0003_sourcereviewnote` and `0004_review_note_guards` in
  the synthetic campaign. The latter installs insert/sequencing validation and
  database UPDATE/DELETE rejection. Existing source/Case/Evidence rows are not
  rewritten. Backup/restore must retain the new application-owned note table too;
  it has normal receipt FKs and immutable audit values.
- Existing V10 dispatcher already imports `views.ACTIONS`; it automatically sees
  `source_return`, `source_note`, `source_simulate`. No new public route or guard
  whitelist entry is needed. `source_filter` additionally accepts optional `query`
  (max 128 characters), states `held` and `files`. Existing form contracts continue
  to work. `source_timeline(case_ref)` remains the case-to-source navigation seam.
- Keep `FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED=False` by default. Only the
  explicitly synthetic demo enables it, along with the existing intake/desk flags.
  Both review-queue scope and the current bound case scope are required. Existing
  `desk_demo` now supports repeated browser scenarios without daily Python calls.
  Integrator may enable that same flag in the V11 isolated demo only.
- `desk_services.record_note` receives `receipt_id`, kind/text, a bounded request
  key, expected note sequence and the existing trusted subject/provider. The same
  key and content is idempotent; changed content conflicts. Concurrent writes with
  one old sequence produce one save and one stale result. Resource authority is
  rechecked before commit. `resolve_review` optionally accepts
  `expected_notes_version`; the UI always supplies it, so a note/hold/reopen makes
  an old resolution form stale without weakening old case/evidence checks.
- Existing source-form proof now carries an operation nonce and notes version.
  All mutation forms remain CSRF-protected, browser-bound and expiring. No cookies
  contain capability tokens. A new split case still grants no staff scope and
  does not reveal a requester capability. Continue through the existing explicit
  identity/scope/recovery process; this lane does not invent U03 permissions.

## Focused verification

Local Python 3.13.16 / Django 5.2.18 / PostgreSQL 17.12:

- **22/22 PASS**: 13 affected V10 source HTTP/privacy tests plus 9 new V11 tests.
  They cover all three browser-simulator contracts, duplicate submissions, foreign
  identities, disabled simulator and forged fields, hold/reopen and stale decisions,
  immutable raw/audit, query/return and cross-case isolation, missing-file filters,
  scope withdrawal rollback, concurrent notes and populated migration guards.
  Initial discovery included the imported base HTTP class; the import now uses a
  module alias so selecting the V11 test class runs its 9 tests only.
- **2/2 PASS early smoke**: existing human followup plus the updated source rollback
  cleanup, which restores the full installed migration graph after introducing
  the dependent note table. The human followup overlaps the 22-test run; counts are
  not additive acceptance claims. No unrelated application suite was repeated.
- **1/1 PASS actual Chromium 154.0.8037.57**: generate a source reply in the browser,
  hold/reopen it, human followup, preserved case-reference search, actual WAV upload,
  playback duration 0.1s, exact downloaded bytes, evidence timeline 1–3, RTL 320/1280,
  keyboard actions and revoked-file 404. Zero external requests/page errors.
  Local `sandbox=False` is explicit; no sandboxed CI/PG18 result is claimed here.
  Artifacts: `.local/qa/v11-source/browser/result.json` and `timeline-320.png`,
  `timeline-1280.png`. Image/PDF elements are implemented but this lane's new browser
  test specifically proves audio; V8 media validation/route contracts remain reused.
- **PASS final checks**: Ruff, Django system check, no missing migrations, and the
  fixture-only demo smoke on PG17 (3 source cases, 2 review tickets, 1 pending
  receipt). A focused search/isolation test passed again after adding Unicode text
  validation to the query; no unaffected suites were repeated.

Commands use the repository's fresh owned database helper:

```sh
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.source_case_intake.desk_settings -- \
  .venv/bin/python manage.py test apps.source_case_intake.v11_tests.V11SourceDeskTests --noinput

# Same helper/profile for the browser module (Playwright must be installed):
# manage.py test apps.source_case_intake.v11_browser_tests --noinput

# Interactive fixture-only UI, or append --smoke for startup checks:
# python -m apps.source_case_intake.desk_demo
```

The preceding V9/V10 failure history stays in its original docs. No V11 functional
test failed in the runs above. The migration-generation command warned that the
default closed port1 target was unavailable; real migration execution/tests use
the fresh helper-owned PG17 cluster. No success is claimed against that closed
default database. Combined V11/PG18/sandboxed Chrome and restored-note integrity
are for the integrator's final exact-head run.

## Acceptance candidate and remaining limits

Ready for human rehearsal: search scoped receipt → generate a local scenario →
review raw → hold with reason → reopen → attach or explicitly split → upload a
declared fixture → follow source/evidence/file timeline → return to the same case
for the existing research, answer, delivery and publication workflow.

Source edits/conflicts, unsupported or captionless media, and missing source
identities remain held. There is no automatic match by name, person merge, source
verification, real external account, live provider, messaging or production grant.
WhatsApp/Facebook/Instagram stay closed. The new note table is additional intake
audit, not an alternative case/evidence/answer system. No scholarly answer or
approval is generated. Gates and historical evidence are unchanged.
