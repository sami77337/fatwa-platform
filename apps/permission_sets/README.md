# Versioned operational permission sets and individual overrides

This optional development application adds versioned templates, per-user
overrides and an immutable change audit above the recovered PR244 continuation.
It does not activate production or change the historical permission laboratory.

## Accepted implementation contract

Sources: D-026, D-067, SPEC-U14-009, SPEC-U14-010, SPEC-U14-011 and SPEC-U14-015
in the saved `docs/product/v12_scope_evidence` source corpus. Owner rows401 and404
require permission sets/individual overrides and an audit record for each change.

- An explicitly selected `OperationalAuthority` adapter consumes stored exact
  action/resource grants. The existing operational identity, source, privacy,
  publication and scholarly boundaries remain independent.
- The single resolver defaults to denial. Any matching DENY from a selected
  template or individual override defeats every matching ALLOW.
- Templates and user configurations are immutable versioned snapshots. The same
  sealed append-only revisions form the audit log. Disable and revert operations
  append a new revision after current authority and source checks; they never
  rewrite or reactivate an old audit row.
- User bindings select stable template identities. Template changes therefore
  preview every affected user and require fresh administrative mandates for all
  of them. A configured user bound to a disabled, expired or unavailable template
  is denied until the binding or template is explicitly repaired.
- The administrative authority is separate from this ledger, defaults to absent,
  and supplies finite candidate subjects/resources plus independent exact
  management mandates. A role or a candidate list never grants administration.
  MUFTI and ORGANIZER_ADMIN use the same administrative contract.
- Self changes and edits of a template bound to the acting administrator are
  rejected. The closed operational matrix cannot contain scholarly authorship,
  answer approval, meaning approval, identity-role changes or management of the
  administrative authority itself.
- Grants have explicit finite deadlines. Current identity role/auth epoch/scope,
  row hashes, source versions, administrator mandates, CAS and response-final
  policy snapshots are checked. A revocation during composition must discard the
  response, not wait for the next request.

The initial executable adapter covers the existing operational workspace. This
does not claim that all other domain authorities or the 70 historical rows have
been migrated into the store. Their current explicit policies remain required.
Gate C/D/E HOLD; production activation remains outside this work.

## Native workflow and resolution

The native forms use the existing Mufti staff session at
`/casework/staff/permissions/` or the actual operational session at
`/casework/operations/permissions/`. Only an actual MUFTI or ORGANIZER_ADMIN with
an independent `ENTER` mandate can open the editor. Both roles use identical
administrative contracts; neither role supplies an implicit mandate.

A template form selects exact existing operational resources and ALLOW or DENY.
A user form selects stable template identifiers and optional individual rules.
The preview shows changed rules and every currently bound user affected by a
template revision. Confirmation is bound to the authenticated subject, role,
authentication epoch, path, browser CSRF secret, current ledger, policy revision,
target identities, selected template versions and exact proposed definition.
Reason, finite duration and explicit confirmation are required. Confirmation
after an intervening change is rejected; a reused request key cannot append a
second audit revision. Reopen the current record to prepare a fresh change.

`store.resolved` follows the latest revision of every selected template. Missing,
disabled or expired templates close their bound profile; this includes its
individual overrides. `store.effects` then combines exact scopes with DENY
winning over every ALLOW. `runtime.StoredOperationalAuthority` also binds a user
profile to the current role, authentication epoch and complete case scope. No
matching ALLOW means denial. Source-specific, media, publication, classification
and scholarly policies still run independently in the existing workspace.

Template changes require `MANAGE_RULE` for the union of old and new rules, even
when removing a DENY. They require current user-management mandates for every
affected user. Disabling and reverting append new audited revisions under the
same checks. Revert copies a historical definition into a new version with fresh
identity, policy, source, CAS and deadline validation; it does not revive a row.

The closed catalog deliberately excludes canonical answer creation/approval,
transcript meaning approval, identity-role editing and administrative policy
management. Those authorities cannot be manufactured by an override. The
existing scientific workflows retain their separate actual-MUFTI checks.

## Composition contract

The coordinator owns shared configuration, navigation and verification registry
wiring. An explicit experimental composition must install `apps.permission_sets`,
include its URLs, and provide all of the following independently:

- `FATWA_PERMISSION_SETS_ENABLED=True`; the default remains false.
- `FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY`: a trusted implementation of
  `PermissionManagementAuthority`. Its pure `projection_epoch` covers mandates,
  finite candidates, exact resources and expiry. Missing authority denies every
  management operation. This authority is never writable through the ledger.
- The existing trusted identity provider and actual role-specific session.
- An explicitly selected `StoredOperationalAuthority` as the operational policy
  if the composition intends that workspace to consume the stored grants.

Candidate subjects and resources are choices, not management grants. Template
creation still needs CREATE_SET plus each exact MANAGE_RULE mandate; future
READ_SET/WRITE_SET remain independent. The helper classes in `test_support`
grant only finite synthetic fixture scopes and are not application defaults.

Grants last 5, 15, 30 or 60 minutes, bounded further by every applicable current
administrative, identity and browser-session deadline. The development bounds
are 64 rules per definition, 16 selected templates per user, 256 revisions per
chain and 8192 audit rows. Changes to those policies require a separately reviewed
composition; no production account hierarchy or policy is accepted here.

## Persistence and verification inventory

`PermissionRevision` is both the definition history and change audit: actual
actor, target identity pins, exact definition, previous hash, policy/ledger
snapshot, reason, request identity, deadline and optional reverted source are
sealed in the same immutable row. PostgreSQL guards reject UPDATE/DELETE,
reordered chains, invalid seals, forbidden actions, self changes and JSON null
values that could otherwise evade three-valued comparisons. All authority and
identity callbacks finish before the final pure ledger/source/deadline checks;
late revocation discards HTML and rolls back a pending write.

Service/native HTTP test labels are `apps.permission_sets.tests`,
`apps.permission_sets.test_http` and `apps.permission_sets.test_recovery`.
`recovery_support` owns one nonempty table, functions `ps_rule_valid(jsonb)` and
`ps_revision_guard()`, and trigger `ps_revision_guard`. Its fixture saves six
template/user audit revisions, verifies twelve named denials, and performs an
actual current organizer read after every denial before reporting success.

The protected browser journey is
`apps.permission_sets.browser_tests.PermissionSetsBrowserTests`, with artifacts
under `.local/qa/functional-continuation/permission-sets-browser/`. It edits a
user override and a template through native preview/confirmation, checks stale
organizer forms, proves DENY wins, disables/reverts a template, and reads the
unchanged original history. Its presence is not a browser PASS; hosted CI must
execute it with the protected browser sandbox.

## Verified local checkpoint, 2026-11-21

The combined service/native HTTP/recovery and existing operational regression
ran 48 tests successfully on PostgreSQL 17.11 (81.543 seconds) and PostgreSQL
18.7 (81.700 seconds), using fresh owned synthetic databases. Labels:

```text
apps.permission_sets.tests
apps.permission_sets.test_http
apps.permission_sets.test_recovery
apps.operational_workspace.test_notes
apps.operational_workspace.tests
```

This includes 24 new permission tests: both actual administrative sessions,
SQL null/immutable-history guards, one-winner concurrent confirmation, fresh
disable/revert, affected-user preview, late revocation, original preservation,
and twelve independently named recovery denials followed by a real positive
read. Ruff and formatting pass. Model migration generation reports no changes.
The protected browser journey and the coordinator's full restored composition
have not been claimed as executed by this local checkpoint.
