# V13 connected synthetic development integration

Base: PR #231, `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`.
Integration branch: `codex/20261118-v13-integration`. One integrator owns shared
configuration, routing, native UI composition and final validation. V12 is retained.
This is development evidence, **not acceptance or a deployment**. Automated
synthetic tests exercise human-review role boundaries and confirmation controls;
they do not constitute a real scholar's approval or expert benchmark review. No new completion
percentage is assigned. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED. No real data, external delivery, production keys, accepted U03 policy,
automated fatwa approval or Meta connector contract is introduced.

## Delivered lane identities

These are actual task/thread identifiers supplied by coordination, not invented URLs.

| Lane | Thread | Delivered commit |
| --- | --- | --- |
| Independent baseline security | `6afc80af-d6a4-8191-a0ac-08f14e1b300b` | `e87790932288c94b0ff6656621d0afac3368bd8c` |
| D6 startup analysis | `6afc807f-d7cc-8191-ad01-1d971f53f019` | `3eaf0c6f6e3f4f696c7a5fe6870790ca482d0ea2` |
| Browser recording | `6afc9ae5-b338-8191-bcff-7654953230ed` | `6e978e7cff7590ea8e78fde7e377c43a36f3ef9a` |
| Timed citations | `6afc808d-03cc-8191-98d8-58fba73eb00c` | `f81bcb762251588a319dddb4b7f4b5b8228cd884` |
| Measured Arabic search | `6afc8096-82c4-8191-98d8-58fba73eb00c` | `fc9f8514c72ccec229a3960f5bfa8e63fcf01b2f` (remote inspected and imported unchanged) |
| Independent classification review | `6afcfb09-8d84-8191-8233-aa8ae1279001` | `fee124fe00920a83ca790f0e10a6f4ab9812b199` |

## Current composition and boundaries

The campaign registers optional applications with literal default-off flags and
no default authorities. `config.settings.v13_review` requires source-rights
checks, maintenance admission and encrypted recovery, and forbids V10 plaintext
compatibility. Synthetic tests initialize explicit owned databases/storage and
supply short-lived exact-scope test policies; there is no deployment configuration.

Classification is private, source-pinned and independently reviewed. It neither
changes the canonical publication category nor creates a knowledge relationship.
Publication/knowledge detail screens expose native navigation to its desk; the
current-case frame comes from the authorized service result, never a browser ID.

Timed references retain an immutable media owner, version, bytes hash, validated
actual duration and bounds. Canonical approval/downstream hooks at `be40a35` reject pending, withdrawn or
expired annotations and re-resolve the scholarly approver for downstream use.
Timed deadlines remain checked through the canonical case transaction and the
existing whole-collection publication filters. Feature enablement alone grants nothing. Book622 remains one
book's table of contents, not its text or an approved global taxonomy.

Recording captures a short PCM WAV into the existing native file form. Explicit
permission/start/stop/preview/accept/cancel and a separate authenticated form save
are required. Browser object URLs are previews only. Structural validation is not
malware scanning. Only synthetic microphone input is permitted in automated runs.

## Evidence accounting

Full local connected browser: test tree based on product `0c8d653` plus the
three V13 browser files committed as `eb018c441021d457be8c9ecc74ac9d733c285408`
passed on PostgreSQL17.12 (257.324s), Chromium154.0.8037.57, **sandbox=False**.
One UI-created case retained five Evidence and six answer versions, three final
answer parts, two confirmed timed-reference revisions, independent classification
rejection/correction/approval, partial simulated delivery and independent
publication/library.84 target HTTP requests verified the separate restored
PostgreSQL server/database/assets, exact recorded bytes and denial after outsider,
case-scope, book-rights and timed-media-rights withdrawal. The source remained
FROZEN and unchanged. This is not PG18 or protected Chrome evidence.

Earlier local browser harness failures are retained: removed import re-export;
saved-audio selector matching a hidden recorder preview; throttle snapshot before
native PDF requests settled; microphone observer injected into PDF frames lacking
mediaDevices; and omitted local isolated pg_dump path before backup. Corrections
preserve assertions and limits: explicit import, audio[src], request completion
before counter snapshot, same-origin/media-capable observation, and early matching
PostgreSQL tool preflight. The sixth full journey passed. No automatic retries,
request-counter reset, permission expansion or sandbox success claim was added.

Measured-search UI at `cd8e221`: two focused PG17 HTTP tests passed after fixture
policy restoration and existing409 status assertions were corrected. PG18 passed
15/15 (two UI, six real-rights adapter, seven pure evaluation). Original read/open/
back source pins remain intact, and no answer is changed by a search. The measured
sample remains expensive (558 SQL statements for four authorized candidates),
not a production performance claim or independently human-reviewed benchmark.

Native audio composition at `908b17b`: seven distinct HTTP/atomic/privacy tests
passed on each PG major across focused batches, plus three actual AudioWorklet
browser tests on PG17 with explicit local sandbox=False. The initial arbitrary
nested transaction was correctly refused by existing queue preflight; composition
now uses the existing `synthetic_queue_atomic`. A test used pre-login CSRF after
rotation and was corrected. The database/storage boundaries were not relaxed.

Timed canonical integration at `be40a35`:11 new,16 upstream and8 affected legacy
checks have passing evidence on each PG major across focused batches. Initial
fixture omissions (private flag, strict registry authority) and an overly broad
new expiry boundary were corrected. Timed expiry is now tracked separately so
legacy book-only empty-result behavior remains unchanged. Native shared HTTP
passes supplement the service checks; sandboxed Chrome is still independently required.

Initial PR232 CI at `908b17b` exposed a real restoration regression on both PG
majors: `restored_schema_mismatch`, refusing release of restored targets. Runs
[V10](https://github.com/sami77337/fatwa-platform/actions/runs/44216988020),
[V11](https://github.com/sami77337/fatwa-platform/actions/runs/44216988151) and
[V12](https://github.com/sami77337/fatwa-platform/actions/runs/44216988013) failed.
The root cause and focused fix are recorded at `0c8d653` in
`apps/platform_recovery/V13_SCHEMA_EVIDENCE.md`: PostgreSQL redistributed a literal
varchar-array cast in the classification partial unique index. Five new checks
and three affected existing restoration checks passed per PG major. The fix
retains uniqueness, predicate values/order, names and complete function bodies.
Actual restored-index tampering still fails and quarantines the target.

Shared classification wiring at `0bf4dba`: PG17 initially two passes plus one
assertion failure (disabled feature actually denies with404, not503); the corrected
assertion then passed alone. PG18 three/three passed. This preserves the failure
and does not describe the PG17 batches as a clean final full run.

Startup diagnostics at `779264a`: six new and29 affected existing Node tests passed
on synthetic loopback peers. No additional startup time, retry, sandbox exception
or changed failure classification was introduced. This is not Chrome acceptance.
Historical D6 remains **ROOT_CAUSE_UNKNOWN**;30001ms was total startup time, not
WebSocket duration. A successful retry on the same SHA does not establish a flake.
See `V13_D6_ANALYSIS.md` for the preserved logs and archive403 limit.

A separate FAST9 browser launch failed on the intermediate head `0c8d653`,
after114 services and31 HTTP checks passed. Its unchanged10-second Playwright
launch did not return a browser object; the journey was NOT_RUN. See
`V13_FAST9_STARTUP.md` for the exact head-versus-merge execution SHAs, log
fingerprints and comparison with the preceding pass. Its cause also remains
UNKNOWN; no timeout increase, sandbox change or flake claim is made.

Baseline security PASS concerns5aff9ba→5ec6373 only. The separate, independently
performed integration review found two actual private-byte disclosure paths on
`1ea53ead8e6166a64b766968efbb63ea00f4c7c1` despite its16 successful workflows.
A late authority callback could revoke identity or timed rights after the last
check. The first fix `8eb1d76` removed redundant callbacks but was insufficient:
a retained final callback could still revoke timed rights. The second fix
`4f71d2e` rechecks READ_MEDIA/CITE after both deadline callbacks. Historical failures
and unchanged negative expectations are preserved in
`docs/security/V13_INTEGRATION_REVIEW.md`. Its **bounded PASS** covers seven
independent tests on PG17.12/18.7 plus two affected tests per major after explicit
attack-executed assertions. The integrator's46 affected timed/library/rights checks
also passed on both majors after the second fix. This is not the designated
external comprehensive V13 review, whose verdict remains **PENDING**.

Historical hosted [V13 run44219214321](https://github.com/sami77337/fatwa-platform/actions/runs/44219214321)
on exact `1ea53ead8e6166a64b766968efbb63ea00f4c7c1` passed84 affected checks and
one full connected browser journey on each PG17.12/18.7, Chrome157.0.8103.50 with
sandbox enabled. The browser independently restored encrypted database/assets,
opened authorized case/answer/file/audio over target HTTP, and denied revoked
rights. All16 workflows succeeded, but this head is **security BLOCKED**, not a
final candidate. Repaired-head hosted results must be recorded separately; no
historical run is attributed to a later documentation or repair commit.

The restored reference XLSX workbook bytes remain unavailable in this Cloud
executor. Coordination verified the specified workbook checksum independently
in its local environment; see the attributed receipt
in `docs/product/v13_scope_evidence/SOURCE_BYTES.md`. The17 date serialization
differences and nine saved formula values are preserved, not represented as a
whole-file string/byte equivalence or recalculation. A historical package identifies
`542.docx` as the owner-authored original and XLSX as derived. Matching the restored
reference workbook and V12 matrix establishes fidelity to that workbook, not
authoring provenance or acceptance. Original Word bytes remain unverified pending
coordination evidence. Do not upload the workbook.

Recovery still requires stopping writers/GC, draining admitted operations and
FROZEN state, a separate encryption key and independently pinned manifest. Unknown
restoration targets are quarantined; no guessed deletion. No protection against
external privileged SQL or production key management is claimed. Main protection
remains unknown after read-only Forbidden evidence; recommendations do not change
GitHub settings.
