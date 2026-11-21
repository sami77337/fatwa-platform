# Organizer publication management

Owner point **99**, `SPEC-U07-002` and the operational scope in D-054/D-067 are
implemented as management of existing immutable publication editions. Actual
ORGANIZER / ORGANIZER_ADMIN identities can read an exact edition, review its
editing/privacy, independently approve publication or withdraw it according to
separate grants. Publication approval is not scholarly approval or delivery.

## Deliberate scope

The existing MUFTI workflow prepares or corrects the edition body. The operational
manager has no body, title or category editing input, no canonical-answer writer
and no scientific-approval entrypoint. An organizer's publication grant cannot
enter the existing MUFTI-only create_edition or case-answer service. Free organizer
body editing would require a separately defined meaning-review contract and is
not supplied or claimed by this unit.

The existing `PublicationEdition` and `PublicationAction` tables retain the exact
copy, author, source answer/decision, evidence version and action actors/times.
The same journals remain visible to the Mufti desk, library preview and recording
reader. No table, migration or parallel publication state is introduced.

## Current exact authority

`FATWA_OPERATIONAL_PUBLICATION_ENABLED` is false when absent and must be declared
false by integrating settings. The existing operational and experimental-publication
features must also be enabled inside the owned synthetic development composition.
Both default authorities remain absent unless explicitly configured.

READ_CASE and READ_PUBLICATION_MANAGER on the `publication_manager` section admit
the page. Four resource grants are independent:

| Operational grant | Independent PublicationAuthority action |
| --- | --- |
| READ_PUBLICATION_EDITION | READ |
| REVIEW_PUBLICATION_EDITION | REVIEW |
| APPROVE_PUBLICATION_EDITION | APPROVE |
| WITHDRAW_PUBLICATION_EDITION | WITHDRAW |

Each `CASE_PUBLICATION_EDITION` resource pins case, edition, content SHA-256,
original answer, scholarly decision and evidence version. The domain authority
must opt into a pure `projection_epoch()` covering every current permission input;
an old unversioned scalar policy cannot authorize the new manager. Existing
MUFTI scalar callers retain their previous contract.

Literal true results, actual subject/role/auth epoch, current configured policy
objects, case scope and finite operational grant deadlines are rechecked before
append and after rendering. Denied exact edition reads remove its body, title,
history, decisions and derived list entry. The separate existing summary grant
still only exposes its authorized operational status.

## Review, publication and withdrawal

Every transition requires a strict native POST with CSRF, explicit confirmation,
exact edition hash, case/evidence versions and current action count. Duplicate or
stale submissions append nothing. Only the newest current edition can be reviewed
or approved. Withdrawal remains possible on a historical edition and preserves
all prior events.

Unavailable current sources do not erase an independently authorized private
editorial history. Its exact READ grant can still show the retained copy, labeled
as needing source/rights review; the manager permits no new review or approval
of that source and can offer an explicitly granted withdrawal.

The operational review must be independent of the edition preparer. The publication
approver must be independent of the preparer, editorial reviewer and scholarly
answer approver; the same existing SQL guard enforces publication independence.
Before a new review or approval, canonical answer authors and scholarly approvers
still resolve as actual MUFTI.
Recording readers resolve publication participants as their actual editorial roles
while leaving original recording/answer authority unchanged.

Approving the journal does not create a library preview policy, anonymous grant,
delivery event, production deployment or account permission. A separately supplied
exact preview policy can read the approved edition; withdrawing it removes that
availability and never resurrects an earlier version.

## Source and response composition

Source rights and citations are independently checked. The retained canonical
source bundle introduced with transcript editing also covers precise and timed
citations for this manager. All permission/identity callbacks precede external
byte reads and all pure policy/source/deadline pins. The source-rights ledger and
configuration are pinned separately from the intentional publication-action append.
Ordinary citation callbacks do not reopen annotation contexts after they close.

One exact existing journal row advances the operational source watermark. An
unrelated callback append, source mutation, canonical-role change, grant withdrawal
or same-epoch policy-object replacement rejects the response and rolls back the
pending action. Integer journal IDs retain their native ordering across 9/10.

## Evidence and remaining limits

Behavior labels:

- `apps.operational_workspace.test_publication`
- `apps.operational_workspace.test_publication_sources`
- `apps.operational_workspace.test_publication_recovery`

`publication_recovery_support` has empty TABLES/FUNCTIONS/TRIGGERS because existing
publication storage is already owned and registered. It restores a Mufti-prepared
copy with organizer review, independent admin approval and withdrawal. Thirteen
named current-trust denials are followed by a real positive read; original/history
row pins remain identical. Stored actions never restore grants or public release.

One native protected browser journey is defined in
`apps.operational_workspace.browser_publication.OperationalPublicationBrowserTests`.
Proof goes to `.local/qa/functional-continuation/operational-publication-browser/result.json`
with operator/admin traces and 320/1280 screenshots. It must pass in the hosted
protected browser before this point receives completion credit; this document
does not claim that execution occurred locally.

Evidence uses owned synthetic cases, explicit grants and Mufti-prepared sample
editions. Detailed production policy, scholarly acceptance and release gates stay
unchanged. The final visual design and free organizer editing of scholarly meaning
are outside this unit.
