# Closed synthetic publication editions

This app adds a working editorial copy/review/independent approval/library workflow
over the canonical `Case`, `AnswerRevision` and `CaseDecision`. It creates no
second case or scholarly answer and never modifies the source. It is an explicitly
enabled experiment, not the public catalog and not production publication.

Both `FATWA_PRODUCTION=0` and `FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True` are
required. The latter defaults to false. Every service also requires the existing
owned synthetic PostgreSQL guard and a current case-scoped MUFTI identity.
`FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY` defaults to `None`; configure a trusted
server instance of `PublicationAuthority` with explicit case/action grants to
exercise approval or withdrawal. No organizer role or wildcard grant is inferred.
The publisher must differ from the editor, redaction reviewer and substantive
case approver. This conservative experimental separation is not a resolved U03
production policy.

## Integration and use

Register `apps.experimental_publication` in the synthetic campaign profile and
apply its two reversible migrations. Delegate POST actions in `views.ACTIONS` to
`views.workspace` at the existing guarded `/casework/staff/` path. All actions
require the normal CSRF-bound staff session and exact form keys. No new public
route, external sender, or production setting is introduced.

- `pub_open` + `case_ref`: approved private source and editorial copies.
- `pub_create` + case reference/revision/evidence version, title/category/body:
  save a new immutable editorial edition. Text is entered separately; private
  question, requester identity and audit notes are not copied.
- `pub_review` + case reference/edition ID/`confirm=yes`: explicit human review
  of text, meaning, title, category, references and personal-data removal.
- `pub_approve`: same fields, independently authorized publisher identity.
- `pub_library` + `query`: search only currently approved publication copies.
- `pub_read` + `edition_id`: individual title/category/reference page, with the
  same current-approval and scope filtering as the library.
- `pub_withdraw`: same case/edition/confirmation fields; immediate concealment.

Corrections create a new edition and repeat review/independent approval. A newer
approved edition replaces the older one in the library; withdrawing it does not
resurrect an older version. New case facts, a new answer or a withdrawn reference
source suppress the publication automatically. Older source/edition records stay
immutable for staff review. Library DTOs exclude case references, requester data,
staff identities, audit history and editorial citation notes. Search uses the
existing Arabic editorial normalization on publication text alone. Categories
are explicitly experimental labels, not an approved global taxonomy.

When `case_citations` is installed, editions snapshot its verified citations for
the exact source answer under the same case lock. They retain original book,
edition, heading, printed location and source hash; they do not fabricate a text
quotation or claim that TOC metadata verifies a scholarly attribution. Every
review/approval/read revalidates citation provenance. No browser citation JSON
or free-form invented reference is accepted.

## Evidence and limits

Ten focused service/PostgreSQL/HTTP tests pass on PostgreSQL 17.12 and Python
3.13.5. They cover independent approval, explicit redaction, source/evidence
invalidation, correction/withdrawal, default gates, role/scope/epoch denials,
cross-case attempts, immutable DB guards, CSRF/extra form fields, and private
search/detail filtering. Browser evidence belongs to the campaign integration
test; this app does not independently claim browser or PostgreSQL 18 results.

```sh
.local/venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin .local/runtime/pg17/usr/lib/postgresql/17/bin --major 17 \
  --settings apps.experimental_publication.settings -- \
  .local/venv/bin/python manage.py test apps.experimental_publication.tests --noinput
```

Human redaction and meaning review are explicit attestations, not automatic PII
detection or AI approval. A production publisher authority, public audience,
taxonomy and acceptance policy remain unresolved and disabled.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.

## V11 editorial continuity

The staff desk now distinguishes immutable approval history from current library
availability. It labels outdated candidates, superseded publications, withdrawals
and changed source/evidence explicitly. Review/approval/correction controls are
shown only for the applicable edition; publication approval and withdrawal also
use the existing trusted `PublicationAuthority`. Hidden controls never replace
service checks. A short timestamped history stays with each edition. No authority,
role, migration, public preview grant or publication record is created by reading
these screens.

The library detail can open the authorized editorial desk with existing `pub_open`
and `edition_id` instead of `case_ref`; supplying both is rejected. The service
resolves and reauthorizes the canonical case. All desk forms accept the optional
pair `library_query` / `library_category`, which carries only bounded search
context. The flow detail → desk → correction → review → independent approval →
withdrawal → library preserves those filters. A withdrawn category remains shown
as the user's selected filter even when there are no available editions. Search
still queries only the existing published-only service projection.

A rejected publication mutation returns an Arabic explanation and a freshly
authorized desk. Failed candidate text is available in a separate, escaped,
read-only copy buffer, never silently rebound to fresh case revisions. Identity
or scope loss suppresses both the desk and that buffer. The shared frame may read
`request.publication_authorized_case_ref`, set only after `services.desk` has
successfully rechecked current identity/scope and before template rendering. This
attribute is not copied from browser fields and is absent on a failed read.

Focused V11 evidence: six new PostgreSQL 17.12 HTTP tests in `tests_ui.py`, the
existing native-forms HTTP contract, and the two V9 library/correction tests passed
(nine distinct tests; affected tests rerun only after changes). Ruff/format and
`git diff --check` pass. Browser and final campaign integration are separate
checks owned by the integration lane; no standalone browser pass is claimed here.
