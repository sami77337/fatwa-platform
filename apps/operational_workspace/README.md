# Operational staff queue under actual identities and current grants

The separate metadata editing and reviewed-classification unit is documented in
[METADATA.md](METADATA.md), with its own default-off flag, grants and proof labels.
The independent lesson-link actions for actual organizers are documented in
[LESSON_LINKS.md](LESSON_LINKS.md), including exact resource grants and source preservation.

This development unit supplies the native operational queue described by original
owner rows **495–500**. Its five lanes read real existing domain state: missing
metadata/classification, failed delivery or reconciliation, publication action,
transcript review and platform capability intervention. No completion credit is
awarded by the implementation or its test count. Exact integrated protected-browser
and encrypted fresh-read evidence remain required.

| Original row | Native behavior and source |
| --- | --- |
| 495 | A separate operational login and queue with authorized counts, exact filters and case detail forms. |
| 496 | Latest OrganizationRevision tags/types, plus the latest reviewed CaseClassification bound to the current approved answer and evidence. Missing items have explicit reasons. |
| 497 | Actual DeliveryIntent failed and uncertain states, with answer revision, logical part ordinal and separate internal-state labels. Only a currently verified exact retry successor resolves its failed ancestors; unrelated failures and unbound claims remain work. A stored DELIVERED state alone is insufficient. |
| 498 | Latest immutable PublicationEdition and its actions: draft review, independent publication approval or changed source. Withdrawal stays visible in detail without reactivating publication. |
| 499 | Latest RecordingTranscript for each original recording, its actual review actions and exact source relationship. MEANING_REVIEW explicitly remains a Mufti review. |
| 500 | Current source origin and configured versioned ChannelProfile compared with each approved answer part's kind, MIME, size and text length. Missing/unversioned capability data becomes an issue requiring attention. |

The direct contract is SPEC-U03-004 with D-054 and D-067. This unit does not close
all of U03. Intake/identity-review desks, assignment mutations, manual priority,
operational metadata editing, transcript editing, publishing, sending and permission
administration are separate functions. The queue and its status detail pages remain
read-only. A separately disabled internal-note action is documented in
[NOTES.md](NOTES.md); it permits only an immutable note under independent current
read/add grants. The queue's source records are actual outputs of existing services.

## Identity and authorization

`FATWA_OPERATIONAL_WORKSPACE_ENABLED=False` and
`FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=None` are the closed product defaults.
`OperationalAuthority` requires an explicit exact current grant and UTC expiry
for each actor, role, case and section. Supported actions are READ_QUEUE, READ_CASE,
READ_METADATA, READ_DELIVERY, READ_PUBLICATION, READ_TRANSCRIPT and READ_CAPABILITY.
Literal `True` is required; labels, a role alone, stored workflow decisions and
historical permission rows never confer a grant.
The development seam accepts identity and grant deadlines at most one hour ahead;
the native session is further restricted to ten minutes.

The actual configured directory supplies MUFTI, ORGANIZER_ADMIN or ORGANIZER.
No identity is fabricated and no role is rewritten. A same-named alternate provider
is rejected. The operational RequestDirectory is a separate request adapter bound
to the actual subject, role, scope and epoch. The existing Mufti validator,
scholarly answer creation and scholarly approval services are unchanged and still
reject both organizer roles.

The operational cookie is independent of the Mufti cookie, lasts at most ten
minutes, is HttpOnly/SameSite=Strict and bound to the browser's existing CSRF
secret. Its path is `/casework/operations/`. The loopback development profile uses
HTTP and therefore the existing explicit non-Secure development-cookie convention;
this is not a production session claim. Login uses the real login request budget.
Queue/detail POSTs use the existing staff budget and reject unknown, duplicate or
action-inappropriate fields. No client role, identity, policy or source snapshot is
accepted as an authorization input.

Every visible case requires READ_QUEUE and READ_CASE. Each lane additionally needs
its independent read grant. A case or section with no grant contributes no
identifier, row or count. Detail POSTs require READ_CASE plus the exact section
grant; changing a hidden field cannot expand scope. Queue cards omit question and
answer snippets. A granted detail may show the literal original question, but does
not disclose requester tokens, recipient addresses, internal notes, publication
bodies, transcript text or media bytes. Those resources require separate features
and permissions beyond operational queue reads.

## Consistent native reads

The shared queue transaction and graph mutex precede sorted canonical case locks.
The projection records exact configured objects, pure directory/policy/profile
epochs, all consumed grant deadlines and an exact source-history fingerprint before
permission callbacks. Positive and negative grants are checked again after the
complete native template has rendered. Current identity, object identity, pure
epochs, source rows, scoped case inventory and expiry are then checked before
returning the response. Late revocation discards the entire generated page; a late
domain append inside the transaction is detected and rolled back.

The fingerprint includes canonical question/evidence/answer/decision/event rows,
requester tracking capabilities, original answer-part metadata and DB bytes,
metadata/classification history, source-origin receipts, actual delivery claims,
attempts, exact retry bindings and signed evidence, publication actions and transcript
history. Validating retry ancestry delegates to the existing composite retry reader,
including its original-media checks. This does not disclose or serve private media
bytes or confer permission to play recordings. The current verifier, its key state,
private-storage object and queue audit head are pinned through final rendering.

Only current internal state is reported. Publication approval history is not a
fresh public-release authorization. A failed delivery stays operational work until
the exact independently approved retry chain has a currently verified signed
DELIVERED leaf. Only that leaf's failed ancestors leave the unresolved count; their
original FAILED records remain visible in detail. STAGED or ACCEPTED retries,
unrelated failed attempts, a newer answer's success and unbound approval claims do
not clear the work. Missing, disabled, revoked or unversioned retry trust cannot hide
failures. Dynamic key-status readers need a pure `projection_epoch()`; static
configured keys are pinned directly. The derived proof is read again after rendering
and rejected if it changes. This reader never issues retries or modifies histories.
Channel comparison does not manufacture a signed delivery plan or approve scholarly
content. Changes to current capabilities are reflected on the next read.

Development read bounds are the directory's maximum 64 explicit case references,
8,192 records per consumed source table and at most 64 distinct recording originals
with transcript histories per case. Exceeding these bounds fails closed instead of
silently truncating rows or claiming complete counts. The native read forms use at
most four application fields plus CSRF; there is no DATA_UPLOAD test override.

## Root composition contract

Shared wiring is coordinator commit
`62537e3c1a5180a09aa72e9d17bee966fa69c9aa`:

- Register `apps.operational_workspace` in the campaign application list and its
  two default-off settings above.
- Include `apps.operational_workspace.urls` in the campaign URLconf.
- Permit the exact existing-guard routes `/casework/operations/` and
  `/casework/operations/login/` for GET/HEAD/POST, and
  `/casework/operations/logout/` for POST.
- Keep login in the login rate budget and other operational POSTs in the staff
  budget. Existing host, loopback, query, body and private response restrictions
  remain in force.

The native pages use plain existing product CSS and keyboard forms. No visual
redesign, new script, network client, transport or public write endpoint is added.

## Evidence and recovery contract

Owned PostgreSQL labels:

- `apps.operational_workspace.tests`
- `apps.operational_workspace.test_http`
- `apps.operational_workspace.test_recovery`
- `apps.operational_workspace.test_retry`

The complete owned service/native/recovery/retry labels passed **27/27** on real
PostgreSQL **17.11 in 58.841 seconds** and **18.7 in 59.078 seconds**, using the
actual shared campaign wiring and product request budget. Coordinator-side logs
are `operational-retry-pg17.log` and `operational-retry-pg18.log`. The five retry
regressions use the actual signed provider and composite retry services from
`16783b3653aad9c6815665bc582e1f66b0c48309`: failure, fresh signed retry, staged and
accepted intermediate states, signed delivery and lifecycle closure; unrelated
failure and unbound-claim retention; current trust loss; and final native-render
proof/verifier replacement. Original failed rows remain unchanged. The earlier
22/22 service/native/recovery runs are not substituted for this final run. Ruff and
diff checks are clean. Protected hosted browser and encrypted fresh-target
integration remain separately required.

`apps.operational_workspace.recovery_support` owns **zero** new tables, functions
or triggers. `populate()` creates seven actual synthetic canonical cases through
existing services, including a real independently approved source answer, a signed
failed provider event, a pending publication edition, a pending meaning-review
transcript and a metadata revision. Five cases are visible under the explicit
fixture grants, one is denied by current policy and one is outside directory scope.
All five queue lanes have nonempty exact read evidence. It pins the existing source
tables and never serializes an operational permission or credential.

`verify_restored()` uses a fresh connection and freshly supplied current operational
directory, authority and versioned capabilities. It checks the exact five lane
counts and details, then executes seven actual denials: disabled workspace, absent
authority, absent configured directory, revoked current identity, revoked case read,
revoked transcript read and expired operational grant. It restores explicit fixture
trust for positive reads and proves source records and delivery audit head unchanged.
These checks are suitable for the encrypted fresh-target drill; merely loading the
rows never authorizes an operation.

Protected browser test:
`apps.operational_workspace.browser_tests.OperationalWorkspaceBrowserTests.test_actual_organizer_queue_filters_and_scoped_details_without_scholarly_authority`.
It requires configured sandboxed Chromium, performs actual native login, keyboard
filters and details for all five lanes, measures 320/1280 RTL layouts, checks current
action/identity revocation and unchanged originals, and writes
`.local/qa/functional-continuation/operational-browser/result.json`, screenshots
and `trace.zip` only after success. `page_errors` comes from a real pageerror
collector; external requests must be absent. No local hosted-browser pass is inferred.

D067 production OWNER_POLICY_HOLD is preserved. Historical permission rows remain
non-granting; this finite explicit development seam does not accept or activate the
production U03 policy. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED. No real-user operation or external message is performed.
