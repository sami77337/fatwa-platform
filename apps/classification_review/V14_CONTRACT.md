# V14: classification to a separate editorial candidate — closed simulation

Verified base: PR#232, `1f08cbb7166f70ec340c495da33ccfc1eda9534e`.
Owned branch: `codex/20261118-v14-classification`. All authored files are within
`apps/classification_review/**`; no shared or `experimental_publication` file edits.
V13 branch/evidence preserved. No child PR, main, GitHub settings, real data/keys,
production, external send or automatic scholarly approval.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.** Leadership's
83%±9 reference is unchanged and is neither acceptance nor a new estimate here.

## Policy inspected before implementation

The inspected base's `docs/operations/V13_INTEGRATION.md` explicitly says the
private classification review does not change publication category.
`docs/product/v13_scope_evidence/V13_UPDATE.md` describes points47/417 as the
experimental ledger, without official taxonomy/tags or category mutation.
`docs/product/v12_scope_evidence/decisions.json` preserves D-067's unresolved exact
permission policy and D-069's separation between book622 TOC and the general
taxonomy; source choice is not a blanket classification or publication grant.
AGENTS retains pending U03/U10 and closed gates. These are repository-preserved
policy evidence, not a claim of a newly fetched or accepted owner policy.

The actual `experimental_publication.services` APIs permit a synthetic editorial
candidate, manual redaction/privacy REVIEW, then independently authorized APPROVE.
They contain no accepted classification-to-publication transition policy. The
existing `ClassificationAuthority` also has no such grant. Therefore V14 implements
**only an explicitly opted-in closed synthetic simulation**, with a separate
`EditorialSimulationPolicy`, never a default/inferred production permission.

## Implemented behavior

1. A human explicitly prepares a new candidate from a currently approved,
   unsuperseded classification and its exact approved reference KnowledgeRevision.
   The wrapper rechecks current publication, answer/evidence versions, source pins,
   classification state, identity, permissions and source rights.
2. The canonical `publications.create_edition` creates a new `PublicationEdition`:
   title/body/citations/answer/decision are copied unchanged from the current
   approved source edition; category comes from the exact human-approved label.
   No posted title/body/category/source text is accepted. The prior edition is
   unchanged and remains in the closed library until separate publication approval.
3. Immutable `EditorialBinding` records the exact classification revision, source
   and candidate edition IDs/numbers/hashes, category and simulation policy ID,
   creator identity/epoch and timestamp. One candidate per classification revision
   prevents duplicate concurrent transfers. A stale candidate requires a new
   classification correction and review; it is not silently refreshed.
4. Manual REVIEW and APPROVE each delegate to canonical `publications.act`.
   Canonical redaction review, current answer, source rights and independent
   publication authority remain mandatory. Additionally the simulated publisher
   cannot be the classification proposer or classification approver. This is an
   explicit conservative drill contract, not a newly accepted role policy.
5. A native UI exposes the candidate, existing editorial text, category, private
   classification reason and TOC provenance to authorized scoped staff. It shows
   action buttons only when current policy/independence allows. History contains
   immutable binding IDs, edition numbers, policy IDs, actors, timestamps and
   canonical REVIEW/APPROVE/WITHDRAW events, without copying source/body/rationale
   into the redacted audit path.

All mutations share the existing synthetic ownership unit and canonical case lock,
with maintenance admission outside the transaction. No guard is monkeypatched.
Policy version changes, late rights/identity withdrawal and stale versions fail
closed; any candidate/binding/action created in the failed unit rolls back.

## Exact integration contract

- Keep `FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED=False` and
  `FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY=None` by default. The existing
  classification/publication/knowledge/citation features still need explicit
  synthetic opt-in. The adapter additionally requires literal True for
  FATWA_SOURCE_RIGHTS_ENABLED, FATWA_SOURCE_RIGHTS_ENFORCED and
  FATWA_RECOVERY_MAINTENANCE_REQUIRED; a legacy composition cannot activate this
  operation by setting only its simulation flag. Do not replace strict campaign
  settings with isolated settings.
- Configure a server-owned `EditorialSimulationPolicy` only for synthetic drills.
  Its nonempty stable `policy_id` (max128 characters) is pinned into every binding.
  `permits` receives provider ID, subject ID, auth epoch, exact case reference,
  exact classification revision ID and `INSPECT`, `PREPARE`, `REVIEW` or `APPROVE`.
  Only literal True grants; absent policy, exceptions, truthy values and changed
  policy IDs deny. Existing classification VIEW and canonical scoped active MUFTI
  identity are also required. Configure INSPECT for intended mutation users.
  The test implementation is a fixture, never an application default/U03 policy.
- Apply app migrations **0003_editorialbinding** and **0004_editorial_guards** to
  owned synthetic PostgreSQL only. The second migration owns an additive trigger
  on canonical `experimental_publication_publicationaction`, active only for
  editions linked by EditorialBinding. It leaves unbound editions unchanged.
  Bound REVIEW/APPROVE require the transaction-local admission set by this adapter,
  current classification/source lineage, and reviewer independence. Calling the
  ordinary `publications.act`/shared pub buttons on a bound candidate is denied,
  so the added policy cannot be bypassed. This does not replace canonical guards.
  Normal authorized WITHDRAW remains available even with the simulation disabled.
- The already integrated dispatcher reads `classification_review.views.ACTIONS`;
  four new actions are included there and delegated to `editorial_views.workspace`.
  New native controls live only in the owned templates. Existing CSRF, loopback,
  throttling, maintenance and no-store middleware must stay installed. Successful
  context derives `classification_authorized_case_ref` from the authorized case,
  never from a submitted value.
- Integration must verify the new table/functions/additive trigger in its exact
  recovery schema manifest/restore path. This slice tested maintenance freeze and
  rollback, not a new full encrypted recovery drill. No recovery verifier was
  edited or relaxed. Preserve strict source-rights enforcement.

### Python API (`editorial.py`)

```python
common = dict(
    publication_id=source_edition_id,
    subject_id=trusted_subject,
    provider=trusted_provider,
    synthetic_fixtures_only=True,
)
prepare_edition(
    **common,
    revision_id=approved_classification_revision,
    expected_revision=case_revision,
    expected_evidence_version=evidence_version,
    confirmed=True,
)  # binding_id, edition_id, number, state=CANDIDATE, mode
inspect(**common, binding_id=binding_id)  # authorized detail, current capabilities
act(**common, binding_id=binding_id, action="REVIEW", confirmed=True)
# Separate later human call with independent identity and publication authority:
act(**independent_common, binding_id=binding_id, action="APPROVE", confirmed=True)
```

`act` returns IDs/state/mode only; it never records classification approval.
`inspect` returns body/source/private reason only after current authorization;
missing/revoked source access returns an error, not a partial source projection.
IDs and decisions remain available through the redacted classification history.

### Native actions

All use `POST /casework/staff/`, native form encoding, CSRF, and exactly `action`
and **source** `publication_id` plus these fields. Extra/duplicate fields, uploads,
client-supplied identities, title/body/category and return URLs are rejected.

| Action | Additional fields |
|---|---|
| `classification_editorial_prepare` | `revision_id`, `expected_revision`, `expected_evidence_version`, `confirm=yes` |
| `classification_editorial_inspect` | `binding_id` |
| `classification_editorial_review` | `binding_id`, `confirm=yes` |
| `classification_editorial_approve` | `binding_id`, `confirm=yes` |

Errors:400 malformed form;403 CSRF/identity/guard refusal;404 unavailable or denied
policy/source/version;503 storage/maintenance refusal. Private errors do not echo
submitted data. Rendering after a mutation reauthorizes inspection; an identity
revoked after commit can receive a closed response while the committed audit is
retained, so consumers must inspect history rather than automatically retry writes.

## Boundaries that remain unresolved

- There is no accepted product policy for transfer/reclassification. This code is
  disabled by default and must not be interpreted as owner acceptance or permission
  to use real materials/users. It introduces no official primary/additional taxonomy.
- Publication approval is independent, not continuously derived from classification
  state. Changing/withdrawing a classification blocks a pending bound candidate
  and its current-detail inspection; it does **not automatically withdraw or edit
  an already independently published edition**. That immutable publication has its
  own authorized withdrawal/correction path and existing ongoing rights checks.
  No automatic reverse transfer, downgrade or old-edition resurrection is inferred.
- Book622 metadata remains TOC only. No full-text quotation, relation inferred by
  similarity, AI classification approval, auto-review or automatic publication.
- After a newer independent publication supersedes the target, current inspection
  denies; the metadata-only binding/event audit remains. Classification bindings
  do not migrate to subsequent editorial editions or new answer/evidence versions.
- The extra DB marker is application admission, not a defense against privileged
  arbitrary SQL. End-user requests cannot supply it. Default-deny service policy,
  current source rights and canonical transaction/identity checks remain required.

Evidence and historical attempts: [V14_EVIDENCE.md](V14_EVIDENCE.md).
