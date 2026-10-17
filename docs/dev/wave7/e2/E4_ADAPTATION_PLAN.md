# Actual E4 adapter and coordinator integration contract

Implemented and tested LOCAL ONLY on top of E2 published b55c4596506aafd3c3d5c3a3c0fee1450fc2d2c2.
Foundation remains 34355f5173667c6167351cf379ad56957d7f35f3. Publication is on hold:
no push, PR creation/edit, issue comment, merge or deployment for this increment.

The coordinator supplied independently accepted E4 local producer
`dd1c92e186f04e383c7d8ff6c92bcdcab9aca60d` as an internal portable patch.
All nine chunks were verified before reassembly. Verified gzip: 18931 bytes,
SHA256 d490f46cf9b60d5dacecf9c0d51f2d0d29ce31e0816d8e7989336687e3d91712.
Verified decompressed patch: 64276 bytes,
SHA256 1810f47de64f4933e75f03d607966faf09a08963e5792f88ca86b0370dee6c3e.
A prior manual local transfer failed verification and was never applied; the
verified resend superseded it. No repeat transfer or remote fetch was used.

Composition exists only in `/tmp/fatwa-w7-e2-adapter`, initially detached at b55.
E4 files are dependency overlays, not changes in the E2 producer branch or patch.
Actual code was inspected before implementation. Search/filter/page uses E4
workflow_items with Page(page_size,(page-1)*page_size); selected detail uses
workflow_item's current DTO and exact SourceSlices. E2 retains its bounded batch
selector, selected-payload SHA check, one bounded list projection, and event history.
The transition service, CLI and review tests are unchanged.

E2 accepts exact/literal/normalized and exposes native #stored-mode. All batch,
intake/review status, q/mode, page/page_size state survives detail/return/reload.
Question search matches E4 API/SSR context; external-ID aliases are removed.
E4's normalized scope rejection is 400, never a partial result or literal fallback.
Invalid modes/offsets fail before SQL; current verified citations disappear after
reference mismatch even when intake readiness is unchanged. No media is fetched.

E5 must supply ONE shared read flag and ONE URLconf, per CONTRACT.md:
WAVE7_READS_ENABLED derives only from FATWA_WAVE7_SYNTHETIC_READS == '1'; any old
WAVE7_REVIEW_READ_ENABLED is an alias, not another toggle. Actual E4 environment,
app, fixed ownership/schema guards are required. Register E2's persisted named
route before the old generic editorial path, then E4 APIs and legacy patterns.
E2 edits no shared settings/URLs and introduces no competing URLconf.

E5 DB labels: existing review_db16 + read_db12 + new e4_adapter_db8, separately
from no-DB review_off6. E4 actual labels remain its own api8 + db10. Do not run
any DB label in the C6/D6 port-1 runner or optionalize a missing dependency.
E6 may use #stored-mode with exact/literal/normalized and the existing controls.
The final assembled committed SHA, browser journey, Windows and new independent
review remain coordinator gates; this local composite is not accepted assembly.
