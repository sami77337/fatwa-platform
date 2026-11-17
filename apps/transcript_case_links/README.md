# Durable synthetic transcript → existing case

Base: campaign integration `fa929a489a04ba1d3f6f7ab9c32b1bc9eb1d53b8` (17 November 2026).
This additive app completes an actual durable journey over the reviewed transcript
workbench and the existing PostgreSQL case model. It does **not** reclassify a
transcript as WEBSITE intake or create a second case store.

## What a user can do

1. Log in with the existing trusted, case-scoped MUFTI session. In the team desk,
   choose **ربط التفريغات بالقضايا** and select an authorized case.
2. Download the supplied fully fabricated example, or export a reviewed v1/v2 ZIP
   from the transcript workbench. Upload it with explicit synthetic acknowledgement.
3. Preview the actual question, segment identity and timestamps; inspect the source
   answer under an explicit **source evidence only, unapproved** label. This saves
   immutable source provenance but changes no case facts yet.
4. Confirm the chosen question's relevance to this case. The service atomically
   appends its exact question text as `CaseEvidence(FOLLOWUP)`, increments evidence
   and case revisions, clears the old approval, appends a staff-attributed case
   event, and stores a permanent link to the exact upload and source external ID.
5. Reopen the case: the normal team workspace sees the supplemental question in
   the same case history; the transcript desk reads its preserved source answer,
   source/segment/pair identity and digests from PostgreSQL. Source answers never
   become `AnswerRevision` or an approved fatwa. Requester status remains text-free.

The case's original WEBSITE question remains byte-for-byte unchanged. `FOLLOWUP`
is the current generic supplemental-fact contract, with an actual MUFTI subject
and `TRANSCRIPT:<link UUID>` audit note, not a fabricated requester action. A case
waiting for requester clarification cannot be advanced by this staff import;
that confirmation is rejected until the requester responds through the existing
workflow. Historical source answers and prior approvals are retained as history.

## Authorization and transaction boundary

The existing `_staff_case` service verifies the owned synthetic PostgreSQL target,
checks the active MUFTI's exact case scope before and after the case lock, and
verifies canonical history. Browser actions reuse `current_staff` and
`RequestDirectory`, including CSRF binding and auth epoch checks. There are no
organizer grants, wildcard scope, caller-supplied role, identity, access token or
approval authority.

An upload belongs to the case and authenticated subject/provider/epoch and pins
the case/evidence revisions at preview time. Confirmation re-resolves authority,
rechecks source bytes and reparses the bundle. A changed case or revoked/replaced
identity rejects the confirmation. A case lock plus unique `(case, external_id)`
ensures concurrent/replayed confirmations create one evidence record. The same
external ID with different artifact provenance is rejected, not silently replaced.

`TranscriptUpload` and `TranscriptLink` have PostgreSQL immutability triggers.
Insert guards bind upload bytes to SHA-256, and enforce same-case upload/evidence/
event, exact version increments, subject, audit marker and question digest. Source
question content is revalidated against the artifact on scoped link reads.
Failure creating the link rolls back the new case fact, revision and event in the
same transaction; the previously saved preview remains available as provenance.

## Integration contract

The canonical profile **`config.settings.campaign_review`** registers the app,
migrations and template overlay. `apps.transcript_case_links.settings` and its
URL module are compatibility aliases of this shared composition. Its existing
staff dispatcher handles the five explicit transcript actions, preserving the
protected team editor and all access-review, inbox and delivery actions.
Everything stays on `/casework/staff/` with the unchanged guard, request budgets,
login cookie path and no-store/noindex/CSP/CSRF protections. Successful transcript
actions reset the display preference to cases, so a previous delivery panel does
not intercept the next case-editor action. Default/public settings are unchanged.

Migrations depend on `casework.0004_case_delivery_guards`. `0001` adds only two
new tables; `0002` adds reversible guards. Reversing/reapplying `0002` retains
populated source and link rows. Reversing `0001` drops these new tables and loses
their provenance; this is not a data-preserving downgrade.

Limits: 192,000-byte ZIPs fit within the unchanged 262,144-byte HTTP body limit;
all questions must fit the core 16,000-character fact limit. At most 32 immutable
previews per case; identical previews at the same case revision/identity reuse
the existing row. Only completed/reviewable bundles are accepted (including a
checkpoint whose reconstructed contents pass every existing review contract).
An unfinished overlap/pairing checkpoint is refused. These are explicit synthetic
development limits, not production file-retention or requester-identity policies.
The bundle remains unsigned source material; hashes establish internal consistency,
while the trusted staff confirmation authorizes attaching supplemental facts.

## Run and verify

Install the repository requirements with Python 3.13. The existing helper creates
and owns a fresh disposable PostgreSQL 17/18 cluster, applies migrations and removes
that cluster on exit. Use a local PostgreSQL binary directory:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.transcript_case_links.settings -- \
  python -m apps.transcript_case_links.demo
```

The demo prints a new local-only synthetic MUFTI credential valid for 45 minutes
and a scoped fabricated case. Open `http://127.0.0.1:8018/casework/staff/login/`,
then follow the above native-form journey. The supplied ZIP is downloadable from
the desk; no real recordings, requester data, external sender or secrets are used.

Focused tests (no old whole-suite rerun):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.transcript_case_links.settings -- \
  python manage.py test apps.transcript_case_links.tests --noinput --verbosity=2

python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.transcript_case_links.settings -- \
  python manage.py test apps.transcript_case_links.browser_tests --noinput --verbosity=2
```

Browser check needs optional Playwright and `/usr/bin/chromium`, or a browser
selected by `FATWA_FASTBUILD_BROWSER`. Chromium sandbox is enabled by default;
restricted local containers may explicitly set `FATWA_TEST_BROWSER_NO_SANDBOX=1`.
The dedicated workflow uses sandboxed Chrome and the canonical profile.

Original slice evidence before canonical integration:
PostgreSQL **17.11**, Python **3.13.16**, Django **5.2.18**; ten focused integration/
HTTP tests passed, including explicit selection from a multi-question v2 bundle,
duplicate concurrency, authority isolation, stale
preview, approval invalidation, rollback, immutable/cross-case guards and populated
`0002 → 0001 → 0002` migration. One real Chromium **154.0.8037.57** test passed at
320×780 and 1280×900: native login → case selection → sample download → upload →
preview → confirmation → fresh persisted read. Two cases linked independently;
a third unauthorized case stayed untouched, no authored answers were created,
RTL/no-overflow passed, and page errors/external requests were zero. Local artifacts
are ignored under `.local/qa/transcript-case-binding/`. Ruff/format, Django system
checks, migration drift and diff checks passed. PG18 and CI are not claimed.

**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.** No main merge, deployment or live
data. Durable synthetic integration is implemented; production identity, retention,
channel delivery and acceptance policies remain outside this slice.
