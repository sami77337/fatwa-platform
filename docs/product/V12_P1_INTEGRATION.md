# V12 connected P1 integration — synthetic evidence, not acceptance

Branch `codex/20261117-v12-integration`; the single Draft PR is
[#231](https://github.com/sami77337/fatwa-platform/pull/231), above V11/#230.
Gate B **NOT_PASSED**, C/D/E **HOLD**, Phase01 **BLOCKED**, **NOT_DEPLOYED**.
Leadership's **79% ±8** remains unchanged. No main merge, GitHub settings change,
real user data, external send, production key, U03 grant or automated ruling.

## Prerequisite and ownership

P1 started only after the owner's explicit P0 opening instruction: independent
review PASS on `5aff9ba3cce35241b3ded27ed3428e0d4ecad768`, 13 focused checks per
PG17/18 including the original multi-result expiry reproducer and concurrent
withdrawal probes. The report-only commit `181685ccb3ffe1fc67f83e0cc129e46dfd14ddce`
is preserved by `742460a`; earlier failures remain in
[P0 integration](V12_P0_INTEGRATION.md) and
[independent review](../security/V12_P0_REVIEW.md).
All 22 workflows completed successfully on that P0 head. CI alone did not open P1.

Internal isolated worktrees were actually used, with one integrator:

| Agent / branch | Owned work | Delivered commit |
| --- | --- | --- |
| `/root/v12_case_journey`, `codex/20261118-v12-case-journey` | `apps/mufti_workspace/**` | `bb28359ce05312c1291938c2e1e790e7b8f26a2d`, integrated `9d3d612` |
| `/root/v12_rights_registry`, `codex/20261118-v12-rights-registry` | `apps/source_rights/**` | `15cfb72211e479958d3217516ac6faff8ff6b312`, integrated `6325416` |
| `/root/v12_connected_browser`, `codex/20261118-v12-connected-browser` | Three new V12 browser/fixture files only | `a2b436c`, integrated `f00d9eb` |
| `/root/v12_integration_review` | Read-only review | No edits; found staged-change evidence attribution issue, fixed `5905e8b` |

The external P2 task is thread `6afc8096-82c4-8191-98d8-58fba73eb00c`, branch
`codex/20261118-v12-scope-evidence`. Its exclusive
`docs/product/v12_scope_evidence/**` baseline commit
`cd8ecfd8b78de3884f7f54226385f228f817fdac` is integrated as `d15c54a`.
The baseline assesses P0 only; P1 evidence refresh is required before final delivery.
These are actual identifiers, not invented task URLs.

## Usable connected changes

The Mufti's selected-case frame now groups source messages, followups and private
PNG/PDF/audio previews by canonical Evidence version, alongside the answer history.
Native controls connect rights, research, citations, editing, human review,
private availability, delivery and independent publication. They navigate; they
do not infer or perform approval. A multipart answer opens the existing multipart
editor, retaining original hashes and old versions instead of offering an
accidental text-only overview edit. An optional untouched native file control now
permits a text revision retaining the old parts; nonempty, duplicate or mixed
forged fields still fail closed. The new revision requires human review again.

The existing source-rights desk inspects exact source/edition/position and input,
archive and snapshot pins. It compares immutable decisions with their actual
predecessors and displays current rights separately from selected history.
Book 622 is **TOC metadata only**. READ, CITE, RELATE and PREVIEW_METADATA are
distinct; FULL_TEXT, QUOTE and original-material PUBLISH remain unsupported and
denied, without new grant controls or inferred licensing. An authorized rights
reviewer's VIEW is not permission to read or publish the underlying material.

The scoped staff library searches allowed source/edition/position metadata as well
as editorial text. One current-rights collection supplies results, categories,
count and bounded pages; P0 collection expiry checks and case locks remain intact.
Native library → publication → knowledge → material → results navigation preserves
the query/category/page and selected case. Only server-derived, reauthorized case
attributes may restore the frame; form values cannot grant case scope.

No parallel case, answer, evidence, queue, source ledger or publication approval
store was introduced. Existing services, permissions and independent approvals
remain authoritative. Slice contracts:
[case journey](../../apps/mufti_workspace/V12_JOURNEY.md),
[rights inspector](../../apps/source_rights/V12_P1.md).

## Focused checks and historical failures

- Case-workspace slice: PG17 initial 21/21 and affected 6/6; PG18 final 22/22.
- Rights slice: PG17 initial 7/8 with one fixture error (the test expired its
  identity as well as source rights), corrected affected 4/4; PG18 11/11.
  Stronger exact-source checks 2/2 per major. Eight new and three existing distinct
  scenarios have passing evidence across those runs; repetitions are not added.
- Integrated services at `0ac1fb8`: 51/51 per PG17/18, both processes exited zero.
  The initial local parallel verifier shared a log path, so its timings/logs are
  not independent artifacts. `3dafd29` separates logs by major; final CI supplies
  isolated exact-head evidence.
- Native multipart browser edit exposed HTTP 400 for the untouched file control.
  Product repair `3dafd29` has three new regressions. Initial PG17 test run also
  had one assertion expecting 404 where complete identity withdrawal correctly
  returns 403; corrected affected test passed. PG18 all three plus the real-file
  upload regression passed (4/4). No authorization check was relaxed.
- Browser attempts before recovery: 19.190s failed at the native-file defect;
  38.454s and 38.600s failed because the network auditor treated Chromium's bundled
  PDF viewer resources as external; 34.915s hit the real staff POST budget.
  Recovery was **NOT RUN** in these attempts. Only the exact bundled PDF extension
  origin and `chrome://resources` are classified as browser assets; all nonlocal
  HTTP(S) and other origins remain denied. The final journey waits for the real
  budget window without erasing counters, retrying rejected writes, raising limits
  or changing clocks.
- The next PG17 browser attempt reached the independent target server, valid
  restore and encrypted negative checks, then failed at 117.962s because three
  read-only inventory assertions used synchronous ORM inside Playwright's context.
  They now use the existing synchronous-worker helper; application behavior and
  the original assertions are unchanged. This attempt is not a full recovery PASS.
- Read-only integration review found no concrete P0/product bypass in catalog
  composition, server-derived case scope, rights inspection, optional multipart
  handling or pending restored-server proof. It identified that `git diff` omitted
  staged changes; the verifier now checks `git diff HEAD` before attributing results
  to a commit. This review is not a substitute for executed browser evidence.

## Final-head verification contract

Local connected PG17.12 run: **1/1 PASS (128.438s)**, Chrome154.0.8037.57,
explicit **sandbox=False**. Source and restored budgets expired naturally after
34.990s and 39.121s; four restored throttle rows were preserved unchanged. The
independent target recorded **68 HTTP requests** against its restored DB/server/
assets, exact PNG/PDF/WAV bytes and approved answer, preserved partial delivery
(three attempts/four receipts), outsider refusal, scope withdrawal and source-rights
revocation. Wrong key/hash/corrupted ciphertext were denied before target creation.
The source stayed unchanged/FROZEN. Receipts are `result.json` and
`restored-http.json` under `.local/qa/v12/browser`; the local run log was
`/tmp/v12-browser-sixth.log`. This is not PG18 or sandboxed-Chrome proof.

The first pushed P1 head `1cedacb` did not launch V12 CI: an unquoted inline YAML
command contained `--only-binary=:all:`. It is now a block scalar and parses
successfully. The missing workflow is **NOT RUN**, not a passing test or a flake.
Product code and browser assertions did not change in this CI correction.

`infra/dev/v12_p1_verify.py` checks the expected SHA and clean tracked files, system
configuration, migration drift, P2 source/build consistency and its six validator
tests, 54 affected service/HTTP/security tests, then one connected browser/recovery
journey. The V12 workflow retains P0 checks and runs this with PostgreSQL17 and18
and **Chrome sandbox enabled on both**. No manual unrelated-suite reruns are needed.
Local browser runs explicitly using `sandbox=False` are not protected-Chrome proof.

The journey uses one case from held source review through clarification/file reply,
research/rights, a human-reviewed text/PDF/WAV answer, private availability,
partial simulated delivery, independent editorial publication and the library.
Delivery means one signed DELIVERED part, one FAILED_REQUIRES_REVIEW part and one
SENT_UNCONFIRMED part, with no automatic resend or reading claim.

Recovery freezes admitted writers/HTTP/GC, creates a Fernet bundle with a separate
temporary key outside repository/artifacts, and rejects wrong key/hash/corrupt
ciphertext before target creation. A **second fresh owned PostgreSQL server**, new
database and private assets are used for restoration. A separate HTTP process
reattaches explicit synthetic identities and public verifiers only, proves the
target DB/server/private root per request, and checks the original bytes, current
answer, outsider refusal and scope/source-rights revocation. The old source remains
frozen and unchanged; no old sender/worker or private signing key is restarted.
Actual run results and CI identifiers must accompany this contract; describing
assertions alone is not a PASS.

## Remaining boundaries

No real source license or full book text was supplied. Public production publication,
Meta provider contracts, real sending, production identity and unresolved U03 remain
closed. Restore control remains an explicit offline drill, not production scheduling
or autonomous failover. Unknown pre-identity targets require manual quarantine;
there is no guessed deletion. Admission covers supported application/command/GC
entrypoints, not arbitrary privileged SQL/Python. Backup encryption is a tested
synthetic facility, not a production key-management or disaster-recovery acceptance.

P2's source has 556 original points, 479 specification IDs and 72 decision IDs in
77 preserved occurrences. XLSX original bytes were unavailable; extracted-text
hashes are not XLSX hashes. Main protection returned Forbidden, so its state remains
unknown and recommendations only. The P0 baseline's partial classifications cannot
be represented as P1 completion or a new engineering percentage.
