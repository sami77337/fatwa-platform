# V11 C — source identity, rights review and availability

Base: PR #229 / `codex/20261117-v10-integration` at
`0f90bb4f6c4ba426055fc77a3a783c2061d6ee19`, verified against GitHub and remote.
Branch: `codex/20261117-v11-source-rights`. Ownership: `apps/source_rights/**` only.
The completed V10 branch is preserved. No shared settings/templates/services changed.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
Synthetic isolated development only. No external send, main merge, production data,
U03 grants, automated fatwa approval or new completion estimate. Owner baseline
74% ±8 is not recalculated here. This is a pilot review candidate, not acceptance.

## Usable functions

The authorized staff workspace searches actual reference editions/positions,
registers exact source identities, records human rights evidence and reviews it
independently. The user can propose/correct rights, reject or revoke them, inspect
history, suggest/correct/review a knowledge relationship, and correct a canonical
answer citation through the existing services.

- `SourceVersion` pins one **actual material position/version**: a ReferenceHeading
  with its work/edition/archive/input/position snapshot, or a same-case TranscriptLink
  with exact bundle/source/question hashes and timing. No supplied text becomes a
  new source. Original book text is not present and cannot be selected as a kind.
- `SourceRegistration` records the scoped actor/provider/epoch/case/time. Registering
  a source changes no rights and no canonical answer/publication data. Repeating the
  same registration is idempotent. A different imported edition has a different
  identity and inherits no grant, even for the same heading title/row number.
- `RightsRevision` is an immutable, **case-scoped** proposal for an exact registered
  version. It records explicitly selected uses, a human-entered documentary basis,
  rationale, expiry and proposer. An independent scoped human reviewer records an
  APPROVE action; REJECT and REVOKE also append their actor, time and explanation.
- A new proposal immediately suspends the prior revision's grant until independently
  approved. Unknown, pending, rejected, expired, revoked, changed-source and missing
  configuration states deny. Approved empty uses mean RESTRICTED. History is never
  overwritten or erased; historical APPROVED/ALLOWED rows do not confer current rights.
- Permitted uses are independently selected: `READ`, `CITE`, `RELATE`,
  `PREVIEW_METADATA`. The last authorizes only a TOC metadata check in an already
  permitted preview, never actual publishing. Private transcripts can only receive
  READ/RELATE and still need the existing private-material access permission.
- Citation correction calls `case_citations.save_cited_answer`, preserving its
  canonical answer text/other citations/media behavior and clearing the old approval.
  Relationship creation/correction/approval/withdrawal calls `knowledge_links`
  services. Rights approval never substitutes for their human review/publication gates.

The evidence basis is a **human declaration in a synthetic workflow**, not a fetched
license, verified legal opinion or proof of real-content rights. No license terms,
rights or scholarly texts are generated. A production evidence/rights policy remains
unapproved. The scope is deliberately one case and exact source position/version;
there is no inferred work-wide, edition-wide, other-case or audience-wide grant.

## Integration contract

1. Add `apps.source_rights` to the synthetic campaign `INSTALLED_APPS`, apply
   migrations `0001_initial` and `0002_integrity`. Templates use existing APP_DIRS.
2. Keep defaults `FATWA_SOURCE_RIGHTS_ENABLED=False` and
   `FATWA_SOURCE_RIGHTS_AUTHORITY=None`. The dedicated settings module demonstrates
   composition; it does not enable the feature. Reference/citation/knowledge and
   publication flags keep their own existing meaning.
3. Route POST actions in `apps.source_rights.views.ACTIONS` to `workspace` at the
   existing `/casework/staff/` dispatcher. Keep the original staff authentication,
   case scope, loopback guard, CSRF, no-store and request budgets. No new URL or
   guard exception is needed. `apps.source_rights.urls` is a standalone test profile,
   not a URLconf to recursively include from shared campaign routing.
4. Add a native CSRF form from the selected case with fields `action=rights_desk`,
   `case_ref`, `query=""`, `edition_id=""`. All operations retain the canonical case.
5. Configure a server-owned `SourceRightsAuthority` implementation. It receives
   provider, subject, auth epoch, exact case ref, action and source-version SHA-256.
   Actions: VIEW, REGISTER, PROPOSE, APPROVE, REJECT, REVOKE. VIEW of the case desk
   uses an empty source hash; source mutations receive the registered identity hash.
   Only literal True grants permission. The existing scoped active MUFTI identity
   is still required; no ORGANIZER/ORGANIZER_ADMIN policy is inferred.

### Enforcement hooks for the integrator

The following are **additional fail-closed predicates**, not standalone authorization
entrypoints. Call them only after establishing the owned synthetic database, the
caller's existing access and the canonical case row lock inside `transaction.atomic`:

```python
from apps.source_rights.services import (
    permits_reference_for_locked_case,
    permits_transcript_for_locked_case,
)

allowed = permits_reference_for_locked_case(
    case=locked_case,
    source={"source": exact_source_snapshot, "source_sha256": exact_source_sha256},
    usage="CITE",  # READ, RELATE or PREVIEW_METADATA at the matching boundary
)
```

Reference source SHA is the existing citation snapshot SHA. Authority source SHA is
`SourceVersion.sha256`, covering the material kind plus that full pinned snapshot;
these are intentionally different hashes. Do not supply a title match or substitute
another edition. Missing registration, changed source, absent/expired approval or
wrong case/usage returns False. A source imported under another edition remains closed.

The transcript hook accepts `case`, `transcript_id`, `usage` (READ/RELATE only).
Preserve the existing OPEN_TRANSCRIPT authority check. Never invoke it to expose a
private transcript in anonymous preview; PREVIEW_METADATA/CITE/PUBLISH are denied.

Recommended V11 composition points:

- Source opening/search results: READ, while keeping current staff access and exact
  source resolution. The rights-review workspace itself must still inspect source
  metadata to review an UNKNOWN source; this does not allow its downstream use.
- New/corrected citations and current citation availability: CITE for each exact
  source in the answer. Keep all answer revision, evidence and human-review checks.
- Relationship proposal/approval and current material navigation: RELATE/READ, plus
  the existing case, publication, independent reviewer and source permissions.
- Library reference projection/open: PREVIEW_METADATA in addition to the expiring
  exact `PreviewPolicy` reference/publication grants and independent publication
  approval. Rights alone cannot populate the library or authorize its body/history.

**This lane cannot enforce rights in untouched callers.** Its workspace adapters
already enforce them for their own citation/relation operations. Shared legacy
entrypoints and the anonymous library still require the coordinator to add these
predicates at their current access/transaction boundaries. Do not claim platform-wide
rights enforcement before those integration changes and affected tests are complete.

### Mutation and concurrency contract

Rights writes and this app's delegated canonical writes serialize using a
case-keyed PostgreSQL session advisory lock (namespace311), acquired **before** any
case row lock, then released in finally. This allows reuse of existing public services
whose ownership guards must run outside a transaction; no guard is monkeypatched or
suppressed. PostgreSQL rights triggers acquire the corresponding transaction advisory
lock and case row lock, enforcing the same order for ledger insertions.

Do not invoke `register/propose/review/correct_citation/propose_relation/act_on_relation`
inside an existing transaction. Do not acquire namespace311 after a case lock.
The locked read predicates do not acquire advisory locks and are safe inside the
canonical caller's existing transaction. New integrated writes may use the predicate
under that case lock directly; they retain their own atomic rollback/version checks.
Tested revocation waits for an in-progress delegated correction, then blocks subsequent
use; concurrent reviews commit exactly one action. No session lock remains after a
failed correction. A change to any upstream transaction boundary needs focused retesting.

## Limits and controls

At most64 registered sources per case, 64 rights revisions per case/source, four
explicit uses, 1,000 characters for evidence basis/rationale, 1–1,440-minute synthetic
review lifetime. The expiry is a development bound, not a production rights rule.
Schema checks reject kind/target mismatch, cross-case transcript registration,
nonsequential versions, unsupported private uses, updates/deletes and self-approval.
Current source snapshots are revalidated on every usable grant, not just registration.

The workspace is private; documentary basis, rationale, identities, internal source
IDs and transcript provenance must never be copied into a public projection. No full
transcript text is copied into the registry or displayed by this workspace. Book622
remains one book's TOC, not a complete fatwa taxonomy, full-text book or verified quote.

## Focused evidence

Python3.13.5 / Django5.2.18 / fresh owned **PostgreSQL17.12**:

- **11/11 PASS** initial service, PostgreSQL integrity and HTTP suite.
- **4/4 PASS** added exact registration visibility, source/input validation,
  concurrent independent review and revocation/canonical-correction serialization.
- **1/1 PASS** additional imported-edition isolation test. These are16 distinct
  service/HTTP/DB tests; successful unaffected tests were not rerun.
- **1/1 PASS Chromium154.0.8037.57**: editor proposes READ/CITE/RELATE/PREVIEW_METADATA
  with a synthetic human evidence record → separate publisher reviews → editor
  proposes a real reference relationship → independent knowledge approval → editor
  corrects the canonical citation, yielding AnswerRevision2 and UNDER_REVIEW.
  RTL320/1280, keyboard focus, no horizontal overflow; zero page errors/external
  requests. Local browser explicitly used sandbox=False; artifact at
  `.local/qa/source-rights/browser.json` contains no private payloads.
- New migrations applied; system check and migration drift PASS; Ruff and diff
  checks PASS. No functional test failed during this lane. Initial migration
  generation warned about unavailable default port1 before real PostgreSQL was
  started; the owned-cluster migrations/tests subsequently succeeded. Import-order
  lint corrections were applied before test execution.
- **NOT RUN:** PG18, sandbox-enabled Chrome, integrated V11 journey/backup/restore,
  real-content licensing or production access. Parent integration owns these checks.
  Prior V9/V10 failures and evidence remain intact in their original records.

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.source_rights.settings -- \
  python manage.py test apps.source_rights.tests

FATWA_TEST_BROWSER_NO_SANDBOX=1 \
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.source_rights.settings -- \
  python manage.py test apps.source_rights.browser_tests
```

The browser executor needs Playwright1.58.0 and Chromium; shared dependencies were
not edited. No child PR is created; the integration owner collects the pushed commit.

## V12 P1 private inspection

The current desk adds a native exact-source inspection, per-use availability and
immutable revision comparison with retained search navigation. See
[V12_P1.md](V12_P1.md) for the action/selector contract, focused PostgreSQL evidence
and explicit unsupported full-text, quotation and source-publication boundaries.
The new regression label is `apps.source_rights.v12_tests`.
