# Provisional fiqh taxonomy, human classifications and reviewed migrations

This disabled development unit implements the connected engineering behavior of
owner rows **159, 161, 162, 164 and 165**. Original inventory text and source pins are
unchanged. The intended exact integrated browser and encrypted-recovery evidence
must pass before this unit receives completion credit.

| Owner row | Observable implementation |
| --- | --- |
| 159 | Human-created multilevel fiqh tree, explicit parent edges and ordering, expandable native outline, immutable saved versions and independent review. |
| 161 | One approved canonical answer can be explicitly classified under multiple reviewed concepts. |
| 162 | One required primary classification and an explicit distinct list of additional classifications; neither list replaces the original answer or approval. |
| 164 | Each meaning has an immutable UUID and definition; display-name corrections and tree moves preserve it. Split or merged meanings receive new UUIDs. |
| 165 | Append-only tree versions, a complete human migration mapping, exact affected-case preview, independent mapping review, actual atomic binding migration, and precise audited rollback. |

The direct specifications are SPEC-U04-003, SPEC-U04-004, SPEC-U04-013 and
SPEC-U04-014, with cross-references U04-001/023/024 and decisions
D-011/017/044/069. The synthetic development tree is **independent** of the accepted
source hierarchy for book 622 and of the owner's separate draft v0.3 global tree.
No scientific taxonomy content, missing branch, scholarly equivalence, production
approval or permission matrix is inferred. This is a functional development engine;
scientific acceptance of the final corpus remains separate and held.

## Native workflow

1. An authorized human opens the existing native staff case workspace and its
   taxonomy tab. A new tree requires a title and provenance. Each concept requires
   a meaning definition; each version records its human author, reason and hash.
   Native form rows specify names and parents, with an explicit add-rows action.
2. A different current human reviews the exact latest version. The author cannot
   self-approve. Rejected or unreviewed versions cannot classify an answer. Read-only
   older versions and their classifications retain their original meanings/names.
3. For the currently approved canonical answer, a human chooses one primary concept
   and zero or more distinct additional concepts. That record pins the exact answer,
   evidence version and reviewed tree version. Later case facts make it historical;
   no classification is silently attributed to a replacement answer.
4. Editing a display name or moving a node creates a new version with the same
   concept UUID and definition. Altering that definition is rejected. Splitting and
   merging meanings use newly created concepts and retain the old version/history.
5. A native comparison starts an explicit mapping for **every** source concept:
   SAME, RENAMED, MOVED, SPLIT, MERGED or NO_EQUIVALENT. The service validates each
   declared relationship against both exact versions. SAME cannot hide a move or
   rename, and SPLIT/MERGED cannot reuse a source identity for a new meaning.
6. The actual dry run enumerates every currently affected canonical case and its
   exact answer, facts, old binding and available target concepts. All affected
   cases and the tree owner must be in current scope. A human explicitly selects
   each primary/additional result or keeps the old binding. A missing equivalent
   **requires** retaining the old binding; the engine cannot guess or drop it.
7. Saving a plan changes no classification. A second human independently reviews
   its exact mapping and impact. A subsequent confirmation performs the complete
   migration atomically, rechecking current scopes and every case/binding version.
   A new affected case, changed evidence, edited classification or revoked authority
   makes the old plan ineligible.
8. Rollback appends reverse classification records and preserves the original plan
   and execution. It applies only while the actual resulting bindings and canonical
   facts still match the recorded migration; it cannot overwrite a later correction.

Native actions are `dt_open`, `dt_save`, `dt_review`, `dt_bind`, `dt_prepare`,
`dt_apply`, `dt_rollback` and `dt_history`, all through `/casework/staff/`. The current
case tab is `dt_open`. There are no public taxonomy writes or new network calls.

## Authority and persistence

Closed defaults are `FATWA_DEVELOPMENT_TAXONOMY_ENABLED=False` and
`FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY=None`. Current authority separately grants
READ, SEARCH, CREATE_TREE, EDIT, REVIEW, USE, BIND, MAP, REVIEW_MAPPING, MIGRATE and
ROLLBACK for exact scoped resources. A historical review record never grants a
current operation. No wildcard, inferred role binding or stored approval is used
as a replacement for the current authority object.

The exact configured identity directory is required, or the existing native
RequestDirectory wrapping that same object. A same-named alternate provider is
rejected. Pure authority/directory snapshots and expiration bounds remain checked
through callbacks and final rendering. Configuration replacement is detected by
object identity. The shared graph mutex precedes sorted canonical-case locks.
Signed ten-minute native state and impact tokens are bound to actor, case, epoch
and CSRF cookie; these carry version pins only, never permission grants.

Seven sealed append-only tables store DevelopmentTree, Concept, TreeVersion,
HumanReview, MigrationPlan, MigrationExecution and CaseClassification. PostgreSQL
validates exact version chains, stable identities, independent reviews, complete
mapping/impact manifests, current canonical bindings, exact rollback and matching
execution authors. A deferred constraint rejects an execution whose full expected
binding set was not inserted before commit. UPDATE/DELETE are rejected.

The development engine intentionally bounds each version to 64 nodes and eight
levels, 256 target edges across a complete migration mapping, 12 additional
classifications, 32 affected cases in a migration, 32 scoped trees, 2,048
versions/classifications and bounded history reads. Service validation and a
PostgreSQL constraint both enforce the mapping edge bound, including databases
upgraded from the previous migration. Exceeding supported
bounds fails closed and requires an explicitly reviewed larger implementation;
this unit does not claim production scale evidence.

The real campaign request budget is 512 fields. Valid maximum native requests use
266 fields for a 64-node tree, 391 for a 64-source mapping with 256 selected target
edges, and 456 for 32 cases with a primary and 12 additional choices each. Native
forms accept only the exact fields for their action; dynamic mapping and resolution
fields must identify an actual source concept or affected case. Unselected
checkboxes are not posted. The HTTP tests use the campaign settings directly,
without overriding either DATA_UPLOAD limit, and execute these maximum valid
requests as well as rejecting unrelated UUID fields.

## Restore contract

`apps.development_taxonomy.recovery_support` exports:

- Seven `TABLES`, each genuinely populated by `populate()`.
- Two `FUNCTIONS`: `development_taxonomy_guard()` and
  `development_taxonomy_complete()`.
- Eight `TRIGGERS`: `dt_tree_guard`, `dt_concept_guard`, `dt_version_guard`,
  `dt_review_guard`, `dt_plan_guard`, `dt_execution_guard`, `dt_binding_guard` and
  `dt_execution_complete`.

The fixture actually classifies two approved cases, reviews a changed version and
mapping, applies it, and rolls it back. Pins cover all seven tables and original
case/question/answer/decision records. `verify_restored()` reads with newly supplied
explicit synthetic authority and a configured directory; it does not reconstruct
trust from database rows. It executes four denied operations, one each for missing
authority, missing directory, revoked reader and revoked mapping permission, then
performs positive reads after restoring current grants. Exact reverse bindings,
sequence 3 on both cases, historical application and rollback are required.

## Executed and pending evidence

Owned service/native/recovery labels:

- `apps.development_taxonomy.tests`
- `apps.development_taxonomy.test_http`
- `apps.development_taxonomy.test_recovery`

**26/26 PASS** on real PostgreSQL 17.11 in 45.259 seconds and PostgreSQL 18.7 in
45.333 seconds. These include actual two-case migration and rollback, split/merge
new meanings, a missing-equivalent hold, independent reviews, scoped/stale/changed
facts denial, concurrent writes, SQL immutability/completeness, impostor-directory
denial, native CSRF/actor-bound forms, rendering-time revocation rollback and
nonempty read-only recovery checks, exact native maximum requests under product
settings and service/SQL rejection of an overbound mapping. Logs are
coordinator-side evidence files `taxonomy-budget-final-pg17.log` and
`taxonomy-budget-final-pg18.log`; no hosted browser
success is inferred from them.

Protected browser label:
`apps.development_taxonomy.browser_tests.DevelopmentTaxonomyBrowserTests.test_native_multilevel_ids_primary_additional_reviewed_migrations_and_rollback`.
It uses configured protected Chromium with `chromium_sandbox=True`, actual native
forms and two distinct authenticated actors. It creates four reviewed versions,
three independently reviewed plans, four real execution records and eight actual
classification records across two cases, including exact rollback, split/merge and
a missing-equivalent case left unchanged. It checks original records, keyboard tree
expansion, current reader revocation and 320/1280 RTL layouts, and writes traces plus
`.local/qa/functional-continuation/taxonomy-browser/result.json` only after success.
Local protected browser execution is unavailable; hosted execution remains pending.

No merge, deployment, real-user operation, external transport or production
migration is performed. Gate B remains NOT_PASSED, C/D/E HOLD, Phase01 BLOCKED,
NOT_DEPLOYED. The preserved original inventories and owner acceptance states are
not changed by this unit.
