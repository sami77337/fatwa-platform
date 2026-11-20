# Scoped data quality dashboard

Owner points468–469 / SPEC-U15-006 and SPEC-U15-007 receive an actual native,
read-only diagnostic workflow. The default flag `FATWA_DATA_QUALITY_ENABLED=False`
keeps it closed. It requires the existing active scoped Mufti, owned synthetic
database, existing request/CSRF/loopback guards and current source/report rights.
No new role or permission policy is invented.

The staff page inspects at most8 currently authorized cases per page. It verifies
required canonical records and event/answer/evidence consistency, saved-author
attribution against the corresponding event, required original attachments,
latest-answer parts/original bytes and exact citation/annotation bindings. It
separately reports authorized unresolved content reports as human review. Optional
transcripts, commentary and enrichment are never required for a healthy result
or for saving a scholarly answer. A revoked source grant is "not checked", not
a claim that its source is broken. No private content, token, source title,
internal actor identifier or storage location appears in diagnostic output.

The whole page, including rendering, remains inside the canonical case/queue,
source-expiry and current identity/policy boundary. Ordered case locks, actor
scope and policy/ledger/case/report snapshots invalidate the complete response
if a callback revokes access or changes the input while it is rendered. An
identity credential may renew its expiry without changing identity or scope.
The page has private/no-store/noindex headers and accepts only its exact native
form fields. It cannot repair, rewrite, approve or publish source content.

Reader feature gates remain pinned through rendering, including their exact
boolean types. The configured source authority and private storage adapter are
also pinned by object identity; replacing either invalidates the composed page.
The reporting policy contributes its current generation only when that feature
is enabled. An absent, unversioned or denying report authority leaves that check
`NOT_CHECKED` and preserves the other diagnostics; a disabled reporting feature
remains explicitly `NOT_APPLICABLE`. Neither condition reports zero unresolved
reports as a successful count.

Actual timed/PDF annotation readers enroll their media policy and expiry in the
existing canonical answer-use boundary. A valid media policy does not need an
unrelated TOC batch generation. Late media permission withdrawal or expiry still
discards the entire rendered response, just as late report withdrawal does.

## Evidence and limits

`apps.data_quality.tests` uses actual PostgreSQL records, physical immutable
originals, current rights and human report transitions. Tests cover missing
physical files, changed bytes, inconsistent event attribution, required missing
records inside a provisional import, recovery after an actual storage restore,
withdrawn rights, scope/policy changes, pagination, CSRF and native HTTP refresh.
The existing deferred SQL constraint independently rejects committing an intake
that lacks its required source; the test retains and verifies that protection.

`apps.data_quality.browser_tests` logs in through the native form and exercises
healthy→required-file-missing→operator-restored→healthy through the visible
refresh button. It requires protected Chromium and records320/1280px RTL
screenshots, no horizontal overflow, no external requests/errors, and unchanged
case/event rows. Browser evidence is claimed only after this test actually runs.

Checks cover the specified required current records, not every possible older
answer/media row, external Internet link, future corpus, or a scientific judgment
about source content. The dashboard reports that explicit scope in its UI.
Unavailable verification is visible instead of being counted as success.
There is no persistent quality table, new media owner, repair job or cached
diagnostic result; recovery remains owned by the source apps already registered.

`apps.data_quality.test_review` adds nine native HTTP regressions for final report
gate/generation/authority changes, unavailable optional report policy, real
original-storage rebinding, reviewed source-authority withdrawal, and valid
timed-media policy use with late permission withdrawal and expiry. These tests
use the actual campaign route, native staff authentication and PostgreSQL.
The combined `apps.data_quality.tests apps.data_quality.test_review` run passed
24/24 tests on PostgreSQL 17.11 in 7.874s and PostgreSQL 18.7 in 8.030s on 2026-11-20,
using fresh owned clusters and the campaign settings. Ruff and formatting checks
passed. These backend/native HTTP results do not replace protected browser proof.

The integrated entry is `/casework/staff/quality/`; forms use the existing
`/casework/staff/` dispatcher actions `quality_open` and `quality_case`.
The isolated development profile is `apps.data_quality.settings`.
Production gates and deployment status are unchanged.
