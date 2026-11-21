# Upload security: recovered boundary and implementation contract

Status: **SEVEN_DOMAIN_ADMISSIONS_INTEGRATED — REAL_ENGINE_ACCEPTANCE_PENDING / NOT_DEPLOYED / GATES_HOLD**.
The initial audit checkpoint was `2fa00ee`. This checkpoint adds the immutable
quarantine and scan ledger, exact-byte receipt controller, bounded single-worker
execution and PostgreSQL integrity guards. A concrete local ClamAV adapter is now
implemented, but no real engine/signature installation exists in this executor.
The seven domain entry points below, their native outer transactions, typed original
readers, library public projections and canonical answer/use boundaries are wired.
The case-bound transcript bundle is the seventh entry. The separate stateless
loopback transcript workbench has no case
database or campaign route; this checkpoint does not claim its upload contract.
Base:
`b456ffd4fe8a00acbf6e1880288e4baaef10b0c4`, following the published
recovery and the current-classification consumer integration.

## Requirement and recovered evidence

Owner 384 requires uploaded files to pass type, size and security checks.
Direct requirement: `SPEC-U11-008`; related source clauses: `SPEC-U11-007`,
`SPEC-U03-034`, and decision `D031`. A failed or unverifiable file must not become
available to readers, parsers, indexes or publication through a retry. Original
bytes remain immutable. The final visual design is excluded.

The recovered source contains structural parsing and type/size limits, but no
ClamAV/clamd/EICAR/antivirus scan ledger or scanner adapter was found across the
available worktrees. Neither `clamscan` nor `clamdscan` is installed in the current
executor. Existing `private_media.filesystem` quarantine is for a corrupt original
being restored; it is not a malware verdict or upload-admission quarantine.

`private_media.validation` bounds ordinary files to 192000 bytes and UTF-8 text
to 65536 bytes. Existing media workers enforce additional PDF, image and audio
structural limits. `private_media.video` has a separately bounded worker for the
allowed MP4/WebM intake. These checks are preserved and are not described as AV.
The staged material importer separately bounds total ZIP expansion to 192000
bytes, rejects compressed/encrypted/unsafe members, and verifies its manifest.

## Actual entry points and transaction boundaries

| Entry | Current composition | Required integration |
|---|---|---|
| `case_attachments.services.upload` | Validates before requester case lock; creates evidence and owner row together | Authorize first, quarantine/scan before the parser, recheck the receipt before atomic owner creation |
| `requester_portal.services.submit_reply` | Adds text then calls upload inside one outer token transaction | Scan before the outer transaction; reuse the same exact receipt inside it; preserve both-or-neither reply/file behavior |
| `source_case_intake.services.attach_fixture` | Holds source and case locks, then calls upload | Preflight the exact declared receipt/source-file/case binding before scanning; keep final binding and idempotency checks |
| `answer_media.services.save_multipart_answer` | Parses files then writes the immutable human answer/parts together | Prepare all new files before the native editor transaction; require current receipts for new and retained uploaded parts |
| `research_library.services.write_material` | May run inside the native editor or import group transaction | Preflight actual library EDIT authority outside that transaction; require receipts before validation and immutable blob/version persistence |
| `material_import.services.stage` and `_parse` | Native stage has an outer transaction; saved input is later reparsed | Scan the outer upload before parsing, and require separate current receipts for every manifest file before later library processing |
| `transcript_case_links.services.preview`, `_entries`, `_upload` | A case-scoped reviewed ZIP was previously reconstructed before authorization | Preflight current staff/case authority; scan the envelope and each bounded stored member before reconstruction, then recheck before preview/link and every source read |

Native outer transactions also occur in `answer_media.views._editor_transaction`,
`research_library.editor.workspace`, and `material_import.views.workspace`.
Moving only the service-level scanner call would therefore leave native uploads
inside a transaction. Native preflight and direct service callers must both be
covered. A prepared receipt may be checked inside an existing owned transaction;
an unprepared external scan may not start there.

Read gates must cover `case_attachments.storage_bindings.raw_for_owner`, actual
uploaded answer parts, `research_library.services._raw` plus version DTO/index
projections, and `material_import.services._parse`. Existing private/public media,
citation and export paths depend on these readers and retain their independent
domain, source-rights, classification and signed-link checks.

Human-authored answer `TEXT`, validated YouTube links, and the original structured
source receipt are not uploaded binary files. They must not acquire fabricated AV
receipts or be silently rewritten to satisfy a file gate.

## Implemented ledger and remaining admission integration

The implementation remains default off and requires an explicit configured
scanner. No executable, signature directory, production credential, network
service, operator grant or malware-free guarantee is inferred.

`integration.prepare_authorized` runs each original domain's current permission
and case/version check, closes it before invoking the scanner, then repeats it
afterward. A current scan receipt is only byte admission; final domain identity,
rights, classification and compare-and-swap checks remain mandatory. Native answer,
library and import forms preflight before their existing compound transactions.
The requester reply and its attachment still commit or roll back together. A
failed compound command retains its independently committed quarantine evidence.

`UploadSecurityResponses` is the shared HTTP wiring requirement: a pure projection
around the final response, without an outer database transaction. Place it after
maintenance/session middleware and before view/CSRF/preview dispatch. It fails
closed for a protected streaming response; current original routes buffer their
bounded bytes. Signed private GET/HEAD/Range routes retain the same pure receipt
checks using the existing `private_media.links.retain_projection` contract.
The app must be installed/migrated; defaults remain the four values in `settings.py`.
No URL or new authorization policy is needed for these native upload forms.

Verification recorded for the integration checkpoints:

- 39 ledger/adapter/entry/admission tests pass on PostgreSQL 17 and 18.
- 14 transcript tests (including the 11 existing binding regressions) pass on
  PostgreSQL 17. The bundle bytes, attached literal question and source receipt
  remain unchanged, and a source answer is not imported as a ruling.
- Nine native HTTP/transcript tests pass on PostgreSQL 18. Actual library,
  enhanced answer and import POSTs prove no outer transaction around the scanner.
  Late rendering revocation rolls back the native library write. Private GET,
  HEAD and Range requests deny stale receipts. The HTTP collector adds no outer
  transaction and rejects a protected streaming response.

These are actual application/SQL/control-flow checks with a declared synthetic
scanner. A protected browser journey, restoration helper and actual ClamAV smoke
artifact are separate acceptance evidence and are not asserted by these tests.

- Retain original uploaded bytes in a separate private, immutable quarantine
  record before scanning. Failed intake must not create a canonical attachment,
  answer, library version, import batch or indexed derivative.
- Retain fixed scan states and exact file/engine/signature/profile identity.
  Only a completed current `CLEAN` receipt may release bytes for structural
  validation and a separately authorized domain write. Missing, failed, timed
  out, stale, malformed or changed scanner state remains unavailable.
- Keep a detected/blocked result sticky across ordinary upload retries; a
  changed filename, caller, request key or disabled flag is not a release grant.
  No new administrative override policy is invented.
- Bound request waiting and concurrent scanner work. A late return cannot write
  a successful receipt or be handed to a later request. A configured concrete
  local process adapter must also bound/terminate its own child process.
- Recheck current receipt and scanner configuration through the existing final
  domain/render/stream boundaries. Preserve digest-lock ordering and the owned
  database guard. No parser, index, public projection or export may use an
  unscanned upload when this contract applies.
- Test adapters must identify themselves as `SYNTHETIC`. A marker-file or EICAR
  response from a stub demonstrates control flow only. Real-engine validation
  remains explicitly `NOT_EVALUATED` until an actual engine and signature database
  execute the owned acceptance case.

## Primary adapter documentation

`clamav.ClamAVScanner(ClamAVConfig(...))` is an explicit local adapter, with no
default executable, inferred version, signature downloads or network daemon.
Configuration requires the actual executable path/SHA256/version, a dedicated
directory containing exactly `main.cvd`, `daily.cvd` and `bytecode.cvd`, their exact
sizes/SHA256 values, the allowed daily-database age (1–30 days), and a memory limit.
The operator supplies these actual values; this package does not invent them.
Construction fingerprints that snapshot outside request transactions. Later pure
projections reject changed inode/content metadata, missing files, unexpected
database members and expired CVD creation timestamps. The process fingerprints
the bytes again before and after scanning, and the engine verifies official CVDs.

Only a strict one-file summary with a matching engine, positive loaded signature
count, and no extra diagnostic lines can produce `CLEAN`. Unsupported switches,
engine errors, malformed output, stale signatures and missing coverage deny the
file. The scanner profile enables encrypted/limit alerts, disables engine cache,
and disables the engine's skip-on-time-limit behavior. A separate process enforces
CPU, memory, file-size, descriptor and wall-clock limits. Timeout kills and reaps
only that process group; the outer single-worker controller retains its slot until
the worker actually exits and never stores its late result.

`ClamAVAdapterContractTests` contains nine synthetic output/control tests,
including an actual worker kill/reap and an actual failed exec. These prove the
adapter contract, not malware detection or signature quality. **Real ClamAV
acceptance remains NOT_EVALUATED** until an operator supplies a genuine installed
engine and current signed databases. No EICAR fixture is passed off as real AV
evidence. The original media structural validator remains a separate requirement.

The official ClamAV documentation states that `clamscan` loads a scanning engine
and database for each run; `clamdscan` cannot enforce engine options itself. It
also documents that some configured size/time limits can cause skipped content.
The adapter must not interpret an unchecked zero exit status as complete coverage.

- [Official scanning guide](https://docs.clamav.net/manual/Usage/Scanning.html)
- [Official clamscan manual source](https://github.com/Cisco-Talos/clamav/blob/main/docs/man/clamscan.1.in)
- [Official clamscan option source](https://github.com/Cisco-Talos/clamav/blob/main/clamscan/clamscan.c)

The documented limit-alert options, fixed return codes, actual scanned-file
summary, loaded signatures, bounded command output, executable/database identity
and current supported options must all be checked. Missing or unsupported runtime
capabilities are an unavailable scan, never synthetic evidence of a real pass.

## Actual-engine acceptance command

`apps.upload_security.acceptance` executes the same concrete adapter and process
limits against one benign synthetic upload and the standard harmless 68-byte
[EICAR installation test](https://www.eicar.org/download-anti-malware-testfile/).
It has no Django/database dependency and writes no product rows or configuration.
The executable and signature snapshot must come from the actual CI installation.
Supply the real canonical paths; do not manufacture CVD headers, signature hashes,
engine versions or a successful command response to satisfy this check.

```sh
python -m apps.upload_security.acceptance \
  --executable /usr/bin/clamscan \
  --database-directory /absolute/path/to/current-official-cvd-snapshot \
  --signature-source https://database.clamav.net \
  --max-daily-age-days 2 \
  --memory-bytes 2147483648 \
  --timeout-seconds 30 \
  --output /absolute/path/to/artifacts/upload-clamav-acceptance.json
```

The signature directory is an immutable, dedicated snapshot containing exactly
`main.cvd`, `daily.cvd`, and `bytecode.cvd`, with no writable group/world bits.
An updater's working directory, a CLD renamed as a CVD, a partial download or an
unsigned test database does not meet this contract. Acquisition is a separate CI
step using the official database source. The artifact labels the supplied source
URL as operator-reported; ClamAV itself must verify the official database format
and signatures without an unsigned override.

The artifact records actual executable/version/SHA256, all database hashes,
sizes/versions/timestamps, profile, exact sample hashes/sizes, coverage, engine
return codes and bounded scan reports. Only both exact verdicts with complete
one-file coverage and a positive loaded-signature count can yield `PASSED` and
`real_engine_verified: true` (exit 0). A wrong actual verdict yields `FAILED`
(exit 1); missing runtime, signatures, freshness, supported options or complete
coverage yields `UNAVAILABLE` (exit 2) with its failed stage. Save the JSON artifact
even on a nonzero exit. This is bounded acceptance for these samples and this
snapshot; it is not proof that every malicious input will be detected.

The local executor run currently returns `UNAVAILABLE` because the engine is not
installed. The two `ClamAVAcceptanceAvailabilityTests` confirm that this state is
written as evidence and cannot become a synthetic pass. Hosted real-engine
acceptance remains pending and is required before owner 384 can be completed.

## Recovery and native browser contracts

`apps.upload_security.recovery_support.populate/verify_restored` owns three
nonempty tables: `upload_security_quarantinedfile`, `upload_security_uploadadmission`,
and `upload_security_scanattempt`. Its SQL inventory is
`upload_security_history_guard()` and the `upload_security_file_guard`,
`upload_security_admission_guard`, and `upload_security_scan_guard` triggers.
It retains a real canonical attachment, a separate blocked quarantine input,
immutable source/owner/ledger fingerprints and exact original-byte checks.
Fresh synthetic trust is reconstructed for authorized reading; restored database
rows do not select a scanner or grant staff access. Reading never invokes a scan.

The explicit `DENIALS` tuple has 14 checks, each expected exactly once:
`disabled_saved_quarantine`, `missing_scan_policy`, `missing_scanner`,
`synthetic_fixture_disallowed`, `changed_engine`, `changed_signatures`,
`changed_scan_policy`, `expired_scan_receipt`, `blocked_exact_bytes`,
`unscanned_exact_bytes`, `wrong_exact_size`, `omitted_app_with_saved_quarantine`,
`missing_current_staff`, and `foreign_case_staff`.
`UploadSecurityRecoveryTests` validates this contract on PostgreSQL 17; actual
cross-database restore is the aggregate runner's separate responsibility.

The native test is
`apps.upload_security.browser_tests.UploadSecurityBrowserTests.test_native_atomic_reply_quarantine_retry_original_download_and_scan_revocation`.
It uses the campaign routes and middleware, real forms, keyboard submission,
file-picker input and an actual original download. The current scanner fixture
is explicitly `SYNTHETIC`: this proves admission and permission control flow,
and cannot replace the real-engine acceptance command above.
It covers missing engine, preserved user draft, both-or-neither reply/file,
sticky blocked bytes despite renaming, successful original download, and denial
of a previously opened original after signature identity changes.

Artifacts are under
`.local/qa/functional-continuation/upload-security-browser/`: `result.json`,
`trace-requester.zip`, `authorized-original.txt`, and screenshots at widths
320/1280 for `unavailable-kept-draft`, `blocked-retry-kept-draft`,
`clean-reply-and-original`, and `revoked-original`. The current local executor
cannot launch protected Chromium because its socket operation is denied. The
test does not disable the browser sandbox and is **not claimed as passed**;
the hosted protected-browser run is still required.

`apps.upload_security.test_privacy.UploadPrivacyCompositionTests` retains every
campaign middleware while enabling classification and upload security together.
It verifies that a current CLEAN receipt cannot replace exact child READ, that
READ cannot override withdrawn scan coverage, and that a final response callback
can revoke either before bytes/headers are returned. The first combined run on
PostgreSQL 17 and 18 found 53/54 passing tests: late denial returned `same-origin`
instead of the required `no-referrer`. The upload middleware now fixes this and
has direct assertions. The matching privacy fix and outer-session retained pure
guards are saved in the coordinator's `6d10f3c7c2f0d7c8b8657fedcfb4101c8328b1b7`.
On that frozen composition plus the added native-session regression, all **55/55**
service/SQL/HTTP/contract tests pass on PostgreSQL 17 (43.484s) and 18 (43.508s).

The added method
`test_actual_session_final_use_callback_cannot_release_old_privacy_or_scan_bytes`
performs actual native login and creates its server session row/cookie. It reaches
an authorized signed Range response before the final real `SessionAuthority.USE`
callback withdraws child READ or scanner signature identity. Both responses are
discarded with 404/no-referrer; exact reads work again after current trust is
restored, and canonical source bytes stay unchanged. The full campaign middleware
remains present. This proves final response composition, not MFA or real AV quality.
