# Reviewed synonym dictionaries and live shadow comparison

## Source and scope

The unchanged owner inventory is `docs/product/v14_scope_evidence/matrix.json`
(SHA256 `0b968605508676f5b3ecb5e84d1f8ab973d1c4e3e448b013765998de3e0fc487`).
The two whole owner-point candidates are **222**, “يدعم Synonym Dictionary.”,
and **247**, “يمكن استخدام Shadow Mode قبل اعتماد تغيير كبير.”
Relevant specifications are `SPEC-U05-007`, `SPEC-U05-027`, and `SPEC-U05-028`;
relevant decisions are D-018, both D-023 occurrences, and both D-044 occurrences.
This implementation does not claim completion of those broader specifications
or decisions, an approved vocabulary, a final benchmark, semantic retrieval,
production search quality, or overall project completion.

## Implemented behavior

- A staff member creates a bounded, immutable dictionary version in ordinary
  Arabic forms. It records the literal authored terms, explicit stable keys,
  alternatives, provenance, provider, actor, authorization epoch, canonical
  digest and exact case/evidence versions. At most 12 terms and three
  alternatives per term are supported. Unknown or repeated native form fields
  are rejected. The full editor uses fewer than 128 fields.
- A later version preserves the previous version and requires a complete
  SAME/RENAMED/MOVED/SPLIT/MERGED/NO_EQUIVALENT mapping with reasons. Historical
  identifiers cannot be silently reused. Every revision has a separate UUID
  and digest; it never edits an earlier dictionary, source, question or answer.
- A real PostgreSQL dry run executes the baseline and candidate queries against
  the current permitted source set. Its immutable receipt binds each query,
  exact generation/document/source versions, result order and additions/removals.
  A different current staff identity must review that exact current preview
  before the version can be used. Approval expires; rejection and withdrawal
  are recorded separately. A previously approved version remains explicitly
  selectable until it expires or is withdrawn. There is no automatic migration
  of the default search engine or destructive change needing data rollback.
- Explicit dictionary search expands only FTS query tokens using parameterized
  `SearchQuery` conjunctions/disjunctions. The displayed original query remains
  unchanged and the alternatives, vocabulary version and reviewer are visible.
  Source opening uses the existing signed, browser-bound exact source route.
  Normal FTS and literal search do not implicitly acquire these synonyms.
  Native dictionary results retain the existing 20-result pages and 160-result
  ceiling.
- Shadow mode actually executes both searches and records baseline and candidate
  result windows, order, source pins, measured duration and failure status.
  The service returns the unchanged baseline. A candidate SQL failure is
  isolated in a savepoint and recorded as ERROR; current identity, permissions,
  source integrity, expiry and retirement still must pass before any response.
  No automatic promotion occurs and one observation is not a quality claim.
- All governed actions require a literal default-off feature flag, a current
  configured identity provider, exact case scope and separately declared
  `SearchAuthority` permissions. A base SEARCH permission grants no dictionary
  or shadow action. The boundary holds through rendering and rechecks pure
  authorization/source/history/expiry state. Late denial rolls back native
  mutation plus response together.

The native entry is the **قاموس المرادفات ومقارنة البحث** button on the existing
canonical search screen. No external network, automatic scholarly judgment,
production adapter, new URL, JavaScript dependency or routing shortcut is used.
The coordinator must add `FATWA_SEARCH_GOVERNANCE_ENABLED = False` to campaign
settings and retain a field-count budget that admits the strictly bounded form.

## Durable schema and recovery contract

Migrations `0005` and `0006` add four append-only tables:

| Table | Purpose |
|---|---|
| `canonical_search_synonymrevision` | Exact immutable dictionary version and mapping |
| `canonical_search_synonympreview` | Actual current-source dry-run result |
| `canonical_search_synonymdecision` | Independent approval/rejection/retirement |
| `canonical_search_shadowcomparison` | Actual baseline/candidate observation |

Three new functions are `cs_governance_result_valid`,
`cs_governance_difference`, and `cs_governance_insert`. Eight new triggers are
`cs_synonym_insert`, `cs_synonym_immutable`, `cs_preview_insert`,
`cs_preview_immutable`, `cs_decision_insert`, `cs_decision_immutable`,
`cs_shadow_insert`, and `cs_shadow_immutable`. They also use the pre-existing
`cs_immutable` function. SQL checks exact canonical hashes, case/version ownership,
bounded complete mappings, reviewer independence, timestamps, source pins and
result differences. Used records reject update and deletion.

`apps.canonical_search.governance_recovery_support` creates a separate synthetic
case, a real canonical index, two dictionary versions, an actual preview,
independent approval and one shadow comparison. Its restored verifier creates
fresh **external test configuration**, not persisted grants, and performs only
reads. It checks exact history/digests, the original source, real expanded FTS,
unchanged normal/literal FTS, exact comparison pins, eight denied reads and
positive reads after each revoked configuration has been restored. The denial
map is `{missing_authority: 2, missing_identity_provider: 2, disabled_feature: 2,
revoked_current_reader: 2}`. No private keys, credentials or fabricated approval
policies are restored from the durable pins.

## Evidence and remaining gates

`local_validation.json` records the commands' labels and log hashes. The full
affected canonical-search suite passed **61/61 tests on PostgreSQL 17 and 18**,
including 17 new governance service/native/recovery tests. The native cases use
real campaign authentication, CSRF, explicit forms and transactional database
state. The recovery adapter was reopened on a fresh connection and verified to
execute no INSERT, UPDATE or DELETE and create no canonical case event. Ruff
check/format and model migration-drift checks passed; the drift command could
not separately check an inactive default database's migration history.

The protected browser identity is:

`apps.canonical_search.browser_governance.SearchGovernanceBrowserTests.test_native_versioned_dictionary_independent_review_actual_fts_shadow_and_retirement`

It uses two actual authenticated staff sessions, creates and previews through
native forms, rejects self-review, approves with a second identity, proves real
FTS results and exact original response bytes, runs the real shadow query,
checks ordinary search remains unchanged, creates an explicitly mapped version,
withdraws the first version, and denies its earlier comparison/current reader.
The expected artifact is
`.local/qa/functional-continuation/search-governance-browser/result.json`, with
`editor-trace.zip`, `reviewer-trace.zip` and 320/1280 screenshots. It has **not**
been executed locally because protected Chromium is blocked by the local OS.
Its browser pass and aggregate encrypted/fresh-process restore pass remain
pending; the authored browser test itself grants no completion credit.

All defaults remain off. **NOT_DEPLOYED; Gate B NOT_PASSED; Gates C/D/E HOLD;
Phase01 BLOCKED.**
