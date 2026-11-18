> V14 extension: [closed classification-to-editorial simulation contract](V14_CONTRACT.md)
> and [executed V14 evidence](V14_EVIDENCE.md). The V13 ledger behavior and evidence
> below are preserved; transfer is a separate default-off operation requiring a
> new candidate and independent publication approval.

# V13 P1-D — experimental classification review

Base: verified remote PR #231 `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`.
Branch: `codex/20261118-v13-classification`. Ownership: new
`apps/classification_review/**` only. No shared files, V12 branches, main,
GitHub settings, deployment, external sending, real data/keys or child PR.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.**
No new percentage, acceptance claim, U03 permission, automatic fatwa approval,
automatic publication or inferred scholarly relationship.

## Behavior and canonical dependencies

This is a private human review ledger over existing `knowledge_links` and
`experimental_publication`. The baseline has no standalone taxonomy application.
The existing `PublicationEdition.category` is shown and used as the initial form
value. Humans may propose an experimental label with a documented private reason;
there is no replacement taxonomy registry, classifier model or inferred category
hierarchy. Neither proposal nor human classification approval changes that
publication field or makes a new publication/knowledge approval.

A proposal must cite an **already independently approved and current REFERENCE
KnowledgeRevision**, belonging to the exact current approved publication. It pins
the source snapshot/hash, knowledge ID/number, publication ID/number/content hash,
and existing category. The source preview reuses `knowledge_links/source.html`.
Book622 stays a reference work's TOC; its path is source evidence metadata, never
a global taxonomy or full-text scholarly proof. Transcript-based classification
is deliberately unsupported in this slice.

- New/corrected suggestions are always PROPOSED, with no automatic decision.
- A different authorized human records APPROVE or REJECT with explicit confirmation
  and a mandatory note. The proposing identity cannot decide its own revision.
- Canonical case locks serialize corrections and conflicting decisions. PostgreSQL
  additionally enforces immutable revisions/actions, source binding, sequential
  same-publication lineage, independent decisions, and one APPROVE-or-REJECT row.
- Correction appends a revision, immediately removes the predecessor's effective
  status and requires fresh review. Old IDs cannot decide the new revision.
- WITHDRAW is terminal for the selected revision and remains possible after source,
  rights or publication withdrawal. A future correction is a fresh PROPOSED revision;
  no prior approval carries forward.
- Every service uses the existing synthetic ownership/case/identity gates and the
  recovery admission decorator. Current source READ/RELATE rights, edition validity
  and auth epoch are rechecked. The existing source-expiry guard surrounds reads.
- The audit-only path preserves ID, actor, time and decision kind, while omitting
  label, source snapshot, rationale and decision notes. It never describes an old
  approval as currently effective. No classification payload enters the library
  projection, public search, requester pages or delivery.

Capacity: 32 series per publication, 64 revisions per series, 80-character label,
1,000-character proposal reason and decision note. This is a bounded experimental
staff facility, not a corpus-wide taxonomy search index.

## Integrator wiring contract

1. Add `apps.classification_review` to the existing synthetic campaign's
   `INSTALLED_APPS`. Apply `classification_review.0001_initial` and `0002_integrity`
   only to a freshly owned synthetic PostgreSQL database. Migration dependency:
   `knowledge_links.0003_withdraw_unavailable_relation`. No production migration.
2. Keep `FATWA_CLASSIFICATION_REVIEW_ENABLED=False` and
   `FATWA_CLASSIFICATION_REVIEW_AUTHORITY=None` by default. Opt in explicitly for
   synthetic scenarios only, alongside existing publication/knowledge/citation
   flags. The local `settings.py` is an isolated test composition; **do not replace
   the integrated `campaign_strict` profile with it**. Preserve strict source
   rights, recovery maintenance, encryption and middleware settings.
3. Implement a server-owned `ClassificationAuthority` subclass. Its `permits`
   receives `provider_id`, `subject_id`, `auth_epoch`, exact `case_ref`, and action
   `VIEW`, `PROPOSE`, `APPROVE`, `REJECT`, or `WITHDRAW`. Only literal True grants;
   missing implementations, errors, wildcard assumptions and truthy values deny.
   Canonical scoped active MUFTI identity remains independently required. Configure
   VIEW with intended mutation grants for the native desk workflow. Test authorities
   are fixtures only, not deployment policy or accepted U03 rules.
4. In `/casework/staff/`'s existing dispatcher, route POST actions contained in
   `apps.classification_review.views.ACTIONS` to `workspace` before ordinary fallback.
   Keep existing loopback, identity, CSRF, throttle, maintenance and private-cache
   guards. `urls.py` illustrates composition without editing shared routes.
5. Add a native CSRF form at authorized publication/knowledge details:
   `action=classification_desk`, `publication_id=<existing edition UUID>`.
   An audit entry uses `classification_history` with the same ID. The lane does
   not edit shared navigation or attach a case frame. Any frame integration must
   resolve scope from trusted services, never posted IDs as authority.
6. Templates are app-local and discovered through the existing APP_DIRS setting.
   No CSS/JS build or shared template modification is needed. Native buttons are
   filtered by current permission and independent reviewer identity; service
   authorization is authoritative and always rechecked on submission.

All HTTP requests are native `application/x-www-form-urlencoded` POSTs to the
existing staff route. All require CSRF plus exactly `action` and `publication_id`.
Extra/duplicate fields, files, client identities and arbitrary return URLs deny.

| Action | Additional fields | Result |
|---|---|---|
| `classification_desk` | none | current authorized sources and private review history |
| `classification_history` | none | redacted audit; safe after upstream withdrawal |
| `classification_propose` | `knowledge_id`, `label`, `reason`, `replaces_id` (blank for new series) | new PROPOSED revision |
| `classification_approve` | `revision_id`, `note`, `confirm=yes` | independent human APPROVE |
| `classification_reject` | `revision_id`, `note`, `confirm=yes` | independent human REJECT |
| `classification_withdraw` | `revision_id`, `note`, `confirm=yes` | terminal WITHDRAW, then redacted audit |

HTTP failures are generic: 400 malformed form, 403 identity/CSRF/guard refusal,
404 unavailable/unauthorized classification, 503 storage/synthetic-guard failure.
Successful HTML is `private, no-store`; failure pages do not echo private inputs.

Python API (`services.py`):

```python
common = dict(
    publication_id=edition_id,
    subject_id=trusted_subject,
    provider=trusted_provider,
    synthetic_fixtures_only=True,
)
propose(
    **common, knowledge_id=reviewed_reference_id, label=label, reason=reason, replaces_id=None
)  # {id, number, state: PROPOSED}
act(
    **common, revision_id=revision_id, action="APPROVE", note=note, confirmed=True
)  # {id, state}; also REJECT / WITHDRAW
```

`desk(**common, history=False)` returns `publication_id`, `existing_category`,
`candidates`, `history`, `audit_only`, `can_propose`. History rows contain current
source availability, historical decision state and **effective** as separate
fields; never interpret `state == APPROVED` alone as current classification.
`desk(history=True)` deliberately sets availability/effectiveness false and
removes private text. There is no public/export/materialization API in this slice.

The service uses existing locked internal adapters `knowledge._edition`,
`_withdrawal_edition`, `_verified`, `_latest`, `_row_permitted`, `_recheck`,
`_digest`, `_state`. They must remain versioned together. It does not bypass a
pre-transaction ownership guard or open a parallel case/evidence/answer store.

## Executed evidence and limits

See [EVIDENCE.md](EVIDENCE.md) and [evidence/](evidence/). Focused tests use existing
synthetic canonical fixtures, real PostgreSQL, actual independent publication and
knowledge decisions, native HTTP/CSRF, concurrent connections, and actual rights
expiry/revocation. UI review uses synthetic materials only.

Reproduce with the existing fresh-cluster helper (executor supplies binaries):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.classification_review.settings -- \
  python manage.py test apps.classification_review.tests

# Repeat with 18/bin and --major 18.
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.classification_review.settings -- \
  python manage.py test apps.classification_review.browser_tests
```

Browser harness: Playwright1.58.0 and `/usr/bin/chromium`. Default requires Chrome
sandbox. This executor could run only with explicit
`FATWA_TEST_BROWSER_NO_SANDBOX=1`; this limitation must not become an integrated CI
default. Artifacts are generated under `/tmp/v13-classification-browser/`.

Integrated dispatcher/config/navigation, sandbox-enabled Chrome, full-campaign
strict maintenance/recovery composition and independent security review remain
integrator verification. No full-campaign or production readiness is claimed.
No concrete security bypass was found during this slice; if independent review
finds one, stop the affected path until fixed and independently reverified.
