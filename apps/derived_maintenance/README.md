# Existing derivative maintenance — development checkpoint

Default off. NOT_DEPLOYED / GATES_HOLD. This checkpoint implements only the existing
payload owners `SearchDocument` and `CandidateBatch`, toward owner points 443 and
509. It does not assert all future AI payload owners, vector search or pgvector.
Point 443 is the existing derivative-maintenance candidate. Point 509 remains
partial: SPEC-U11-020 also requires saving a newly generated transcript from a
different engine. There is no ASR engine or new automatic-transcription owner in
this implementation. Rebuilding citation candidates does not satisfy that clause.
Original sources: SPEC-U15-019, SPEC-U11-020, SPEC-U12-027, SPEC-U14-023 and
D-016/D-038/D-039/D-046/D-055/D-068, in the retained V12 source evidence.

Explicit finite administrative grants authorize a native preview, current CAS and
confirmation. CLEAR removes actual derivative rows while preserving source data,
human answers, annotations, reviews, notes and immutable generation/run/outcome
headers. An independently retained metadata-only clearance journal precedes SQL;
older SQL fails closed until an authorized reconciliation replays current clearing.
No logical source RESTORE revives a cleared payload or makes its old identifier usable.

Search rebuilding calls the existing canonical current-source reader and creates
a new generation. AI regeneration requires the human to provide the previous
bounded fragment anew and calls only the existing central gateway, with a new
request/run, current source permission, separate processing permission, model pins,
output firewall and fresh checks after provider execution. Real model output may
differ. No actual AI provider, embedding model or scientific-quality acceptance
is configured here. The actual role remains MUFTI for existing source rebuild
services; an administrative CLEAR grant never impersonates a Mufti or grants
scholarly approval. Maintenance authority, domain use and source privacy remain
independent.

Two immutable metadata tables retain clearances and exact old-to-new rebuild
lineage. SQL guards permit deletion only for the exact payload manifest in the
same transaction as its clearance, block reinsertion under a cleared parent and
preserve the old source/history immutability guards. A locally owned private
journal uses the existing suppression journal filesystem checks. Its distinct
format cannot be accepted as a suppression record. The 387 format and validator
are unchanged; only its existing atomic file replacement was extracted.

## Initial checkpoint evidence

The ten initial core tests passed on PostgreSQL 17.11 in 15.939 s and PostgreSQL
18.7 in 16.463 s (`derived-core-pg17.log`, `derived-core-pg18.log`). An earlier
failure exposed an ambiguous SQL variable/alias and was corrected; that run is
not a pass. The initial `c976b53` commit was a saved continuation point; subsequent
recovery, native and callback-order evidence is recorded below. Hosted integration
and protected browser acceptance are independent gates.

Neither 431 nor 450 is counted. The current local PostgreSQL installations have
no vector extension files and the repository has no configured embedding adapter;
traditional text retrieval alone does not prove a vector-service outage fallback.
The exact database capability probe and current owner inventory are below.
Shared config, URLs, aggregate registry and counters belong
to the integrator. Native paths are `/casework/staff/derived-data/` and
`/casework/operations/derived-data/`, admitted only by the explicit feature flag.

## Recovery adapter checkpoint

`apps.derived_maintenance.recovery_support` owns two nonempty audit tables, five
SQL functions and six additional triggers. It creates both cleared and newly
rebuilt owners, while preserving an actual human answer, approved precise
citation and scholarly approval in their original tables. The separately retained
clearance floor stays outside the database/private-file capture.

Populate this component after the existing search/AI populations, immediately
before record suppression. Wrap all later search/AI use and all restored
verifiers in `current_floor(pins["derived_maintenance"])`, composing the separate
`record_suppression.recovery_support.current_floor` around the same readers.
Neither floor context changes an identity, source/AI grant, management mandate or
privacy permission. A missing or stale independently supplied floor fails closed.

The restored verifier performs fifteen named denials and then actual positive
search/source and regenerated-candidate reads. Its rollback drill keeps a newer
external clearance while restoring older SQL, proves ordinary use is refused,
reconciles that clearance with audit, proves the old identifier still cannot
open, and permits only a new explicitly rebuilt child. The drill uses an isolated
external copy and rolls back its SQL; captured history and human originals are
checked unchanged afterward.

`apps.derived_maintenance.test_recovery` passed **2/2 on PostgreSQL 17.11
(26.784 s)** and **2/2 on PostgreSQL 18.7 (26.230 s)**. The second test runs the
existing canonical search, AI gateway and suppression restored verifiers inside
both independent floor contexts, with both management authorities absent outside
their explicit fixture trust. Logs: `derived-recovery-pg17.log` and
`derived-recovery-pg18.log`. These checks do not replace the hosted aggregate
dump/restore or protected browser gates.

## Final callback ordering correction

A separate review found that the outer maintenance callback could revoke AI
processing or source rights after the inner owner had performed its last check.
The previous 154-case regression pass did not prove this ordering. Five new
tests failed on PostgreSQL 17.11 in 9.817 seconds: some unauthorized operations
returned success, and others refused only after a CandidateBatch had committed.
Log: `derived-callback-red-pg17.log`.

Rebuild scopes now retain their exact owner/source guards, AI grants and privacy
projection. The maintenance boundary runs every administrative callback first,
then every retained byte verification, then only pure owner/source/AI checks
while its transaction remains open. Earlier AI stages are linked into the next
stage's final checks and retained by the session response lease. The same hook
retains the actual canonical search scope. The existing search/recording finish
sequence is separated into callbacks, byte verification and pure pins without
removing its checks or granting a new identity or permission.

The five new service cases plus six native HTTP cases and the current-session
clearance case passed **12/12 on PostgreSQL 17.11 (26.371 s)** and **12/12 on
PostgreSQL 18.7 (26.373 s)**. The new service cases revoke USE, PROCESS_CONTEXT,
source READ/CITE after `terminal(SUCCEEDED)`, and search REBUILD after its owner
returns. They require rollback with no CandidateBatch/rebuild audit, a REVOKED
AI outcome, or no new SearchGeneration, followed by a separate positive rebuild.
Logs: `derived-callback-green-pg17.log` and `derived-callback-green-pg18.log`.
The broader regression and additional final-session source cases remain a
separate follow-up; protected browser acceptance is still not asserted.

## Current payload-owner inventory and semantic-search limits

The inventory covers the executable owners in this continuation. The central
gateway's contract, model constraint and SQL guard restrict its sole implemented
task to `CITATION_CANDIDATES`. Its sole provider execution call remains
`apps.ai_gateway.execution.invoke`; this app adds no model, transport, prompt
family or alternate execution path.

| Owner | Current contents | Maintenance treatment |
| --- | --- | --- |
| `canonical_search.SearchDocument` | Original-text copy, normalized text, PostgreSQL `tsvector`, source pins and sealed payload | CLEAR removes all rows of the exact admitted generation; REBUILD creates a new generation from currently allowed originals. |
| `ai_gateway.CandidateBatch` | Validated candidate ranges and the sealed duplicate payload | CLEAR removes the exact batch; regeneration uses a new bounded gateway request and identifier. |
| `SearchGeneration`, `GatewayRun`, `GatewayOutcome` | Actor, request/model/source/version/hash metadata and terminal status | Preserved audit; old cleared identifiers stay unusable. Raw rejected model output is never persisted. |
| `public_answer_media.RecordingTranscript` and its actions | Human editorial versions and explicit meaning reviews | Preserved human history. Its model permits `EDITORIAL` / `MEANING_REVIEW`, not an AI-generated transcript owner. |
| `transcript_case_links.TranscriptUpload` / `TranscriptLink`, FAST5 / FAST8 | Imported transcript bundle, exact text/times, human edits and evidence binding | Preserved originals and evidence. The existing pipeline parses/reviews submitted text and performs no automatic transcription. |
| Canonical search dictionaries and Arabic search evaluation records | Human-reviewed configuration, benchmark corpus, judgments and evidence | Preserved history/configuration, not disposable live index rows. |

CLEAR permanently retires the exact old derivative parent; it does not suppress
the original or revoke separately granted ordinary owner operations. The
maintenance REBUILD form requires its own explicit mandate and records lineage.
An independently authorized ordinary Search REBUILD or new gateway request still
requires current source/domain/processing grants and creates a new identifier;
neither old-request replay nor logical source RESTORE can revive cleared payload.

The actual owned-database probe was run on PostgreSQL **17.11** and **18.7**:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name IN ('vector', 'pg_trgm') ORDER BY name;

SELECT extname, extversion FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname;
```

Both returned only `pg_trgm` version **1.6** (available and installed), with no
`vector` row. The observed outputs are prefixed `DERIVED_CAPABILITY_PROBE=` in
`derived-final-pg17.log` / `derived-final-pg18.log`, and repeated in the final
owner regression logs. `SearchDocument.vector` is PostgreSQL full-text
`SearchVectorField`, not an embedding vector. There is no configured embedding
adapter or semantic vector index in the inspected application. Point **450**
therefore remains unimplemented, and point **431** still needs an actual vector
service and a verified outage/fallback path. The test where an unavailable AI
citation provider leaves FTS usable is narrower evidence and does not close 431.

## Native journey and integration contract

`apps.derived_maintenance.browser_tests.DerivedMaintenanceBrowserTests` declares
one protected journey on **`config.campaign_urls`**, without replacing a product
view or registering test-only URLs. It clears both owners through native review
and confirmation, regenerates them, opens the human answer through real search,
shows candidate positions against the current original source, checks unchanged
human edits/approval, and verifies a revoked management mandate followed by a
positive audit read. It requires `FATWA_BROWSER_SANDBOX=1` and Chromium's sandbox.
It retains its trace on failure and writes PASS only after assertions and cleanup.
Artifacts: `.local/qa/functional-continuation/derived-maintenance-browser/`.

The regenerated candidate page is a full RTL native response, held inside the
current gateway read boundary. It shows the original source and candidate range,
and links to the existing human citation editor. It never opens the gateway's
AJAX fragment as a standalone page or saves a human citation automatically.

The integrator registers this app and its two URL patterns and retains default-off
`FATWA_DERIVED_MAINTENANCE_ENABLED`, with `AUTHORITY` / `JOURNAL` unset. Local HTTP
tests compose the actual campaign middleware with the app URL adapter until that
registration; the protected browser explicitly requires the actual campaign URL
configuration and will fail if registration is missing. No production setting,
aggregate counter or acceptance receipt is changed by this app.

## Final owner-phase and journal-bound follow-up

The owner regression at `4fee4cf` ran 174 tests on each PostgreSQL version: 173
passed and one failed. The failed recording-storage test still armed its callback
by patching the old combined `RecordingSources.finish` wrapper; the coordinated
source boundary now invokes `verify_bytes` and then `final_pins` directly. The
follow-up `918f156` patches the actual `verify_bytes` phase and preserves both the
required denial and `fired == [True]`. All production references were inspected;
`canonical_search.policy` is the only owner of this source boundary, and it runs
both phases. No product denial was weakened.

The same follow-up bounds the encoded clearance journal before atomic file
replacement. Previously its reader rejected a file over 8 MiB but its writer could
replace the current floor with such a file. The new PostgreSQL regression lowers
the limit temporarily, proves rejection before replacing the original bytes or
deleting payload/creating a clearance, then restores the real limit and positively
clears the exact payload.

Thirty targeted tests passed on PostgreSQL 17.11 in **92.007 s** and PostgreSQL
18.7 in **93.115 s** (`derived-followup-pg17.log`,
`derived-followup-pg18.log`). These cover the complete recording-search module,
the five last-maintenance-callback rollbacks, both final native-session response
denials, all eight derivative integrity cases, and both independent-floor recovery
compositions. This resolves the sole earlier owner-test failure and the new
journal-bound risk; it does not relabel the earlier 174-test run as a full pass or
claim a local protected-browser pass. The app now declares 37 service/native
tests, in addition to its one protected-browser journey.
