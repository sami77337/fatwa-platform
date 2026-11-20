# Case organization and internal notes

This optional development module adds an independent metadata history to the
existing canonical case. `FATWA_CASE_ORGANIZATION_ENABLED=False` by default;
operation requires the owned synthetic PostgreSQL profile and
`FATWA_PRODUCTION=0`. It creates no new role or case-access grant.

## User workflow

From an authorized case, open **تنظيم القضية والملاحظات الداخلية**. Enter up to
16 case-specific tags, choose any of the 17 documented question types, and
optionally append an internal note. Leaving the type empty explicitly preserves
an unresolved classification. Multiple types are supported. Tags do not become
permanent attributes of the requester, and the feature does not infer a ruling.

Every saved change appears in the history with its author, time and metadata
version. Editing tags or types preserves the earlier snapshot; a new note is an
append-only historical entry. Private notes are not answer text and are absent
from requester and publication projections. The existing taxonomy remains a
separate system; this feature does not create taxonomy categories or AI proposals.

The organization search accepts an explicit tag and/or question type, optionally
combined with a case/text query. Authorization precedes metadata lookup. Results
contain authorized case references and their organizational labels, not internal
notes or unauthorized counts. Leaving both filters empty still permits ordinary
search; missing metadata never hides an otherwise matching case by default.

## Versions, integrity and stale forms

`OrganizationRevision.version` is the case's metadata version. Saving it does not
change `Case.revision`, `EvidenceVersion`, original evidence, answer revisions,
approval, delivery or publication. A write requires current canonical revision,
evidence version and metadata version. A stale form returns HTTP409 with the
current authorized state and a separate bounded copy of the rejected attempt;
it does not silently rebase or overwrite another editor's change. An identical
command UUID and payload can be retried idempotently; reusing that command for a
different payload is rejected. A blank no-change command is also rejected.

The service validates every history snapshot and its SHA256 before projection.
PostgreSQL enforces consecutive versions, immutable records, unique commands,
bounded versions/arrays, recognized question types and digest shape. Canonical
case locking serializes concurrent writes. Batch search locks cases in the same
UUID order as assignment queues, then rechecks the complete scope and current
case revisions before returning. Identity rechecks pin subject, role, active
status, scope, epoch and provider namespace. A refreshed still-valid expiry
alone does not falsely invalidate stable authority.

All public readers and writers use the existing maintenance admission decorator.
Native forms keep CSRF, exact-field validation and the authenticated browser
directory. Only `question_types` may repeat; all other duplicated fields are
rejected. The synthetic campaign's bounded 32-field limit permits all 17 explicit
types with the existing form pins. No browser-supplied role, user identifier or
arbitrary metadata field is accepted.

Bounds: 256 history entries per case, 16 distinct tags of up to 48 characters,
17 distinct documented types, and 2,000 characters per internal note. The
synthetic profile intentionally does not claim an unlimited production archive.

## Trace and verification

Related owner points: 47, 166–167, 171–174, 224–225 and 436. Internal notes also
support the existing Mufti workspace contract. Related detailed specifications
include U01-014, U02-032, U04-006/008/009 and U05-004/009. These are trace links,
not blanket closure of a broader taxonomy, search or AI requirement.

Run `apps.case_organization.tests` through
`infra/dev/with_casework_postgres.py` with `apps.case_organization.settings` or
the integrated `config.settings.campaign_review`, on PostgreSQL17 and18. Tests
cover approved-answer preservation, metadata conflicts/idempotence, new-evidence
rejection, actual scope/epoch/provider revocation, explicit search, invalid
values, database immutability, native forms, CSRF, maintenance and all17 types.

The connected native browser journey is
`tests.casework.test_functional_completion_browser`; encrypted recovery is
`tests.casework.functional_recovery`. Both are run by the integrated verification
workflow. Their execution receipts, rather than this document, establish whether
a particular commit actually passed. Recovery includes the nonempty table
`case_organization_organizationrevision`, its sequence and its immutable guard.

**NOT_DEPLOYED. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.**
