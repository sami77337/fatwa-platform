# V14 independent security review — BLOCKED on e8ebef8

## Integrated-head verdict (2026-11-18)

**BLOCKED** on **`e8ebef812d7e7cd3411252a8fe11fedb0ab2cc94`**, remote
`codex/20261118-v14-integration`, Draft PR #233. Both remote refs matched before
and after execution. New independent tests reveal two remaining security
boundaries: late identity revocation in evaluation review, and direct PDF/audio
reads outliving their grant during the final media epoch read. The affected
paths and campaign/P2 clearance must remain pending repair and independent retest.

SEC14-01/01B original reproducers now pass unchanged. The byte-for-byte diff of
both earlier external search test files against reviewer commit `3204bbf` is
empty. The new ledger-only final read occurs after policy/identity/epoch callbacks;
strict scope, exact pins and expiry checks remain. This closes those specific
reproductions at this head, not the new findings below. Historical failures and
prior lane-only dispositions remain intact after this section.

## SEC14-02 — evaluation's final authority callback follows its last identity check

Affected: `apps/arabic_search_eval/review.py`, particularly `decide` and `history`.
Each calls `workspace._recheck(...)` and then its final `_permit(...)`. That last
explicit authority callback can invalidate the actor while returning its prior
literal True. `_staff_case` does not re-resolve the actor on exit. There is no
later identity check before commit/response.

New independent methods in `test_final_boundaries.EvaluationReturnBoundary`:

- `test_last_authority_callback_cannot_commit_decision_after_identity_revocation`:
  create a real pending synthetic evaluation, invoke its independent reviewer,
  then set that reviewer's directory identity inactive during the second/final
  APPROVE callback. The callback executes once. The service returns successfully
  and **one EvaluationDecision is persisted** despite the inactive reviewer.
- `test_last_view_authority_callback_cannot_disclose_after_identity_revocation`:
  invalidate the editor during the second/final VIEW callback. The actual corpus
  and judgement history returns rather than denying.

Both fail on PG17.12 and PG18.7. The real identity provider, evaluation rows,
review service and transactions are used; only the explicit authority callback
is wrapped. These are deterministic callback identity mutations, not a claim of
concurrent SQL or an unauthenticated endpoint exploit. The tests assert the
attack ran and do not use xfail. The mutation result is a synthetic evaluation
approval, **not a scholarly fatwa approval or actual human gold validation**.

Repair must revalidate current identity after the final authority callbacks and
before returning or committing, with rollback of a late-invalid decision.
Inspect `propose` as well: it has the same ordering, though the supplied
reproducers specifically exercise decision and history. Keep independent reviewer,
exact dataset/judgement/ranker binding and explicit per-query review requirements.

## SEC14-03 — direct PDF and timed-audio bytes can expire during final epoch read

Affected: direct `pdf_citations.services.open_pdf` and
`timed_citations.services.open_audio` (and inspect analogous locator operations).
Their inner `projection_expiry_guard` checks deadlines before the surrounding
`_staff_case` exits its `media_projection_boundary`. For these direct locator
reads the outer `_answer_use_boundary` has no contributed annotation deadline.
A final pure atomic media epoch read can span the deadline, keep the same epoch,
and return bytes after the inner guard's last clock. The library-specific
post-epoch clock fix does not cover these services.

New independent methods:

- `PdfFinalEpochExpiry.test_pdf_bytes_cannot_outlive_deadline_during_final_epoch_read`
- `AudioFinalEpochExpiry.test_audio_bytes_cannot_outlive_deadline_during_final_epoch_read`

Each creates and confirms a real locator, first verifies that a normal open
returns the exact original bytes, then models elapsed time during **only the
outermost exit epoch read**. The unchanged epoch is returned; policy/grants/source
are not mutated. The deterministic clock crosses `valid_until` by one second.
The injected boundary is asserted to execute exactly once. Actual results return
**671 original PDF bytes / 1644 original audio bytes** instead of denying, on
both PG17.12 and PG18.7.

This is a clock-boundary regression, not forged epoch input or a grant change.
Keep the policy's atomic, side-effect-free contract. Ensure final exact deadlines
survive until *after* the final epoch read for direct byte and metadata operations,
as well as canonical approval/use and library projection. Do not add a final
permission callback that can mutate another grant after checking it.

Initial media probes inspected only the immediate Python caller, which was
unittest.mock's dispatcher, so their attack-executed assertions failed before
exercising the suspected boundary. Both logs are retained. Corrected probes
identify the actual exit frame through the stack and require the sole outer
scope; the two affected methods were rerun and now fail on the actual leaked
bytes. No application code, rights rule or negative expectation was changed.

## Coverage and evidence on this exact head

Read AGENTS, current scope/decision constraints, lane contracts, actual changed
services/migrations and the full internal mixed-media failure history. Executed
focused checks instead of all campaign suites. All runs used actual fresh owned
PostgreSQL17.12/18.7, campaign_review and explicit synthetic fixtures. Reviewer
changes were overlaid into a detached exact head, with no tracked product edits.

| Independently executed batch | PG17.12 | PG18.7 |
| --- | --- | --- |
| Original external search 6 + internal mixed-media 8 + final search callback 2 | 16 PASS, 17.852s | 16 PASS, 17.949s |
| New V14 encrypted schema restore 1 + prior tampered-target reproduction 1 + selected affected contracts 11 | 13 PASS, 17.580s | 13 PASS, 17.478s |
| New evaluation identity probes (first run) | 2 FAIL, 0.525s | 2 FAIL, 0.500s |
| Evaluation diagnostic plus initial media injection attempt | 2 product FAIL + 2 injection assertion FAIL, 1.986s | 2 product FAIL + 2 injection assertion FAIL, 1.961s |
| Corrected direct-media expiry probes only | 2 FAIL, 1.292s | 2 FAIL, 1.342s |

Final observed outcomes across **33 distinct methods: 29 PASS / 4 FAIL per major**.
This is not a green combined-suite run. The reused integrator methods are identified
by their recorded labels, not claimed as newly authored reviewer tests. The original
SEC14-01B assertion has not been weakened. Ruff/format and whitespace checks pass.

- Search/batch: original late-policy and ledger regressions pass; malformed/changed
  epoch denial, post-identity expiry, exact scalar source parity, pages/count/facets,
  mixed-edition rights and immutable validation receipts were exercised. The four
  authorized source sample is now **32 SQL** on each major after the added final
  ledger reads, not the earlier lane's 24. This remains a sample, not an SLO.
- Evaluation: static checks preserve current revision, exact corpus/judgement hashes,
  ranker source hash, independent reviewer, full explicit judgements, append-only
  records, and new-version PENDING. SEC14-02 prevents current authorization clearance.
  **Human relevance quality remains PENDING**; synthetic tests do not supply gold.
- Classification/publication: independently reran the separate manual review and
  independent publication approval, canonical-action bypass denial, FROZEN denial,
  late rights revocation/inspection rollback and competing approval test. These pass;
  the separate simulation policy and canonical source/Evidence checks remain. This
  does not accept unresolved production classification policy or U03 permissions.
- PDF/canonical use: forged page/version/digest, changing identity/scope, omitted
  app/disabled editor with persisted locators and READ_MEDIA/CITE revocation across
  downstream surfaces pass. The internal cross-kind audio withdrawal during PDF
  checks and library epoch-read expiry adversary also pass on this exact head.
  SEC14-03 independently blocks the direct locator read surfaces.
- Recording: read the actual JS delta and native integration. Explicit user start
  calls getUserMedia; only acceptance assigns input.files; pending/recording/preview
  blocks submit. Interrupt/watchdog paths cancel, tracks/ports/contexts/URLs are
  released, and frame/byte caps remain. No network upload API or policy widening was
  added. This is static review plus separately attributed hosted runtime evidence;
  the reviewer's **local protected microphone runtime remains NOT_RUN** due the
  previously documented sandbox limitation. No sandbox bypass was attempted.
- Maintenance/restore: independent encrypted roundtrip preserves complete source/
  target schema and original synthetic private bytes, and keeps source FROZEN.
  New assertions verify all five V14 tables and all six PDF/evaluation/editorial
  guard functions/triggers on the restored target. The original altered quoted
  predicate target still rejects/quarantines. This local fixture proves new schema
  and original assets, not a locally repeated full V14 populated browser journey.
  The hosted journey is separate evidence. External privileged SQL is not covered.

Durable logs, precise support labels and SHA-256 manifest:
`tests/v14_security_review/evidence/final_e8ebef8/`.
Reproduce new failures using the existing wrapper with matching PG17/18 binaries:

```sh
FATWA_TEST_PG_BIN="$TEST_PG_BIN" V12_PG_BIN="$TEST_PG_BIN" \
  python infra/dev/with_casework_postgres.py --pg-bin "$TEST_PG_BIN" \
  --major "$TEST_PG_MAJOR" --settings config.settings.campaign_review -- \
  python manage.py test tests.v14_security_review.test_final_boundaries --verbosity 2
```

New recovery label: `tests.v14_security_review.test_final_recovery`.
Other exact labels are in `support_labels.txt`; regression batch labels are
`tests.v14_security_review.test_search_repair`,
`tests.v14_integration_security.test_crosskind`,
`tests.casework.test_v14_search_final`. Old standalone reviewer branch lacks the
new product applications; run against this reviewed integration head with only
reviewer tests overlaid, or import the reviewer commit into integration.

## Hosted proof is real but does not override the new failures

Independently fetched job metadata and decoded logs for run **44238104547**:
job134579044254 (PG17.12) and job134579044703 (PG18.7), both completed/success at
exact `e8ebef8`. They record109 affected checks plus one connected Chrome journey
per major, Chrome157.0.8103.50, sandbox=true,320/1280 widths, no external requests
or page errors, independent encrypted target READY/HTTP PASS, unchanged FROZEN
source and preserved partial delivery. Minimal exact-head extracts are preserved.
The connector returned17 PR workflow runs for this head, all successful; its
first-page response is not independent verification of the parent's20/20 count.

Both browser receipts explicitly record **pdf_plugin_selected_page=NOT_VERIFIED**.
No screenshot or successful #page=N navigation is promoted to rendered-page proof.
These existing receipts do not execute the four new external challenges. They
remain historical successful bounded runs at a now-security-blocked head, not
proof that the findings are resolved. Do not credit affected security behavior
from green CI alone or relabel the old successful/failed evidence.

Handoff: fix SEC14-02 and SEC14-03 in owning product/integration files; keep this
lane test/report-only. Run focused affected checks and return the exact repaired
integrated SHA for independent re-review. No formal acceptance, new engineering
percentage, main merge, production, external sending, real data/keys or GitHub
settings changes. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.

---

# Historical search-lane review — repair still BLOCKED

## Search-lane re-review at e5c504b (2026-11-18)

**BLOCKED** on `e5c504bb51157a67865ed2547d7fb67a38842117`, remote
`codex/20261118-v14-search`, verified before and after tests. The original
SEC14-01 reproducer now **PASS** on PG17.12 and PG18.7 unchanged. However, a
stronger actual-ledger late-callback challenge fails on both majors. This is a
lane-only assessment; no final V14 integrated-head verdict is issued.

### SEC14-01B: final custom policy callback can revoke the authoritative ledger

`reference_batch.recheck_locked` reloads the ledger, compares the whole batch,
then performs a final per-row policy pass. A callback in that final pass can call
the existing authorized `source_rights.services.review(..., action='REVOKE')`
for an earlier source. No authoritative ledger check follows that callback.
The outer policy epoch remains unchanged because the *custom research policy*
has not changed: only the separate canonical rights ledger has changed.
`projection_expiry_guard` detects time expiry, not a newly inserted REVOKE action.

Independent reproducer:
`tests.v14_security_review.test_search_repair.SearchRepairBoundary.test_ledger_revocation_during_final_policy_pass_closes_response`.

- Independently approve READ rights for two synthetic registered headings.
- During the later heading's third READ_METADATA callback (the final whole-set
  policy pass), call the real authorized ledger review service to revoke the
  first heading. Assert the service returned and the attack occurred once.
- Query with `page_size=1`. Expect denial before any response projection escapes.
- Actual result contains the revoked first heading's title, full source metadata
  and exact resource pins, **total=2, pages=2, next_page=2, facet count=2**.
  The test fails on PG17 and PG18. The snapshot/epoch mechanism did not reject it.

This is a same-transaction real service mutation via a deterministic callback,
not direct SQL tampering or evidence of simultaneous cross-connection revocation.
The wrapper never changes `SyntheticRights.denied`, its identity or epoch. The
research policy still grants; the authoritative source ledger veto should apply.
A REVOKE service call is stronger evidence than just toggling a fake permission
boolean. The repair's existing rank-time ledger test covers an earlier boundary
and does not cover this final-pass mutation.

Required correction: make the final authoritative ledger/provenance check occur
at a coherent boundary after callbacks capable of changing it, including final
identity/authority checks. Avoid adding another callback after that check which
can recreate the gap. Keep policy-epoch and expiry checks, case scoping, source
hashes and current-revision rules intact. Do not make the epoch of a separate
custom policy an undocumented substitute for the canonical ledger. Rerun both
unchanged original and new late-ledger regressions independently before closure.

### Other independently executed checks

- Unknown/malformed epoch (`None`, empty, boolean, integer, oversized string) and
  a changed valid epoch deny. No scalar fallback or silent grant was observed.
- Expiry induced after the final identity recheck denies the entire projection,
  including an empty-match response and a later page; the attack executes once.
- Four-authorized-source query measured **24 SQL** independently on each major.
  Source metadata/digest match the canonical scalar source; no internal rights
  revision is emitted; totals/facets/page hints match the authorized matches and
  human_review remains PENDING. This does not rerun the historical 558-query
  baseline, prove load performance, or establish human-reviewed ranking quality.
- An attempted catalog input-hash mutation is rejected by the existing database
  immutability trigger before projection returns; the original hash remains.
  The first test incorrectly expected CaseConflict and got IntegrityError. Both
  initial logs remain. The corrected test specifically asserts that real DB
  guard; it is not claimed as a successful post-mutation projection recheck.

| Independently executed batch | PG17.12 | PG18.7 |
| --- | --- | --- |
| Unchanged original + late ledger + epoch | 2 PASS / 1 FAIL, 1.126s | 2 PASS / 1 FAIL, 1.145s |
| Counts/pins/SQL + expiry + initial catalog expectation | 2 PASS / 1 ERROR, 1.149s | 2 PASS / 1 ERROR, 1.232s |
| Corrected catalog guard only | 1 PASS, 0.280s | 1 PASS, 0.324s |

Six distinct methods have final observed outcomes **5 PASS / 1 FAIL per major**
across these focused batches. This is not a clean full-module PASS. No expected
failures/skips or weakened security assertions. Test source and original
reproducer are overlaid into a detached exact target; no product files changed.
Logs/manifests: `tests/v14_security_review/evidence/search_e5c504b/`.
Use the existing fresh-cluster command below with label
`tests.v14_security_review.test_search_repair` at the repaired product head.
The module inherits the unchanged original reproducer, so it executes once there.

### Other lane contracts inspected, not cleared

Read the exact PDF `fbf06a03db093aeafbdf38321d18c8f81fc7bfbf`, classification
`ae75b1dc54a87e3421c98bde7efc5b358925f840`, and recording
`397bd75344dc4e14bfa5c992addcef072eabaaf9` handoff contracts. No execution/clearance
of those product deltas is claimed in this search-focused review.

Integration review must specifically verify PDF approval/downstream guards and
expiry propagation even when editing is disabled or persisted app rows survive
restore; classification's independent publication policy and additive DB trigger;
and recorder explicit acceptance, protected assets, maintenance rejection and
resource cleanup. New tables/triggers must survive the exact encrypted recovery
journey. Their reported sandbox-disabled local browser receipts do not replace
protected Chrome evidence. This reviewer's historical local microphone runtime
remains NOT_RUN. Final disposition awaits the nominated integrated SHA after
repair, not merely any remote integration branch observed during discovery.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No acceptance,
percentage change or production authorization. Baseline history follows intact.

---

# Historical baseline review — SEC14-01 BLOCKED

## Exact baseline and scope

On 2026-11-18, both remote `codex/20261118-v13-integration` and PR #232 head
matched **`1f08cbb7166f70ec340c495da33ccfc1eda9534e`**. The clean reviewer checkout
created `codex/20261118-v14-security` directly from that SHA; V13 and its evidence
remain preserved. Read AGENTS.md, the owner lane instructions, current V13 scope
and repair evidence, integration boundaries and relevant source services. No
`.agents/skills` exists in this checkout. Current lane ownership supersedes the
historical foundation/PR instructions; only this report and
`tests/v14_security_review/**` are changed.

**BLOCKED for the affected measured-search projection boundary at the baseline.**
Actual V14 product delta review is **PENDING** until the implementers publish
exact heads. No V14 remote branch was present during initial discovery. This is
not a completed review of a future V14 integration head or a platform acceptance.

## SEC14-01 — earlier search result survives a later policy revocation

Affected baseline: `apps/arabic_search_eval/services.py:search_reference_titles`.
The selected-hit loop authorizes and opens each resource separately, then calls
`research_workspace._recheck`, which rechecks actor identity only. An earlier
resource can become denied by the explicit research rights policy during a later
resource's READ_METADATA callback and still appear in the returned results.
The strict source ledger is necessary but does not replace this separate policy.

Independent real-PostgreSQL reproducer:
`tests.v14_security_review.test_search_boundary.SearchProjectionBoundary.test_later_result_policy_callback_cannot_leave_revoked_earlier_title`.

1. Create a canonical synthetic case and two reference TOC headings through the
   existing fixture services; grant independently reviewed strict ledger rights.
2. Verify the normal `عنوان` query returns both headings, in order.
3. Arm a mutable explicit research policy after ranking finishes. During the
   second heading's READ_METADATA callback, withdraw permission for the first
   heading only. All later policy calls for that first resource return False.
4. Require either a denied response or a result collection without the first
   resource. Assert the revocation callback actually executes exactly once.

**Observed on PG17.12 and PG18.7:** both headings are returned, including the
revoked first heading's title/source/resource pins. The isolated run exposes
`['1:2', '1:3']`, despite `1:2` now being denied. The regression fails with
`An earlier revoked title survived the later callback` on both majors.

The test uses real source/identity/ledger/open services; it wraps only the
explicit policy and ranking boundary to deterministically exercise a late policy
change. It does not mock the authoritative ledger predicate, directly mutate
rights tables, or claim concurrent database revocation. The grant remains valid
in the ledger: the additional explicit policy has been revoked. The distinction
matters because case row locks alone cannot serialize arbitrary external policy
state. No real corpus, private user data or external requests are involved.

Required repair contract for the affected V14 search/batch owner: ensure the
whole emitted collection is authorized at a coherent return boundary after later
resource/policy callbacks. Do not solve this by dropping the explicit policy,
using a batch grant from another case/edition/use, weakening strict rights,
suppressing the reproducer or marking the stale row as merely informational.
If a bounded policy snapshot/epoch contract is needed, make it explicit and fail
closed on change. Add tests for an early resource revoked while a later resource
is built; derive metadata/facets/counts/pages only from the final authorized
collection. Repair and independent recheck must precede affected-path clearance.

## Executed evidence

| Baseline batch | PG17.12 | PG18.7 |
| --- | --- | --- |
| Initial discovery: existing expiry method + new callback method | 1 PASS / 1 FAIL, 2.234s | 1 PASS / 1 FAIL, 2.277s |
| Isolated new callback regression | **1 FAIL**, 1.150s | **1 FAIL**, 1.146s |

The initial module imported a prior TestCase class by name, causing Django to
rediscover its existing expiry test. Changed the import to its fixture module;
no test assertion changed. The isolated rerun confirms the new failure alone.
All four logs and their SHA-256 manifest remain in
`tests/v14_security_review/evidence/baseline/`. No full suite was rerun.
Ruff check/format and git whitespace checks pass; the security regression
intentionally fails until the product is repaired, without xfail or skips.

Run with matching PG17/18 binaries and synthetic settings:

```sh
FATWA_TEST_PG_BIN="$TEST_PG_BIN" V12_PG_BIN="$TEST_PG_BIN" \
  python infra/dev/with_casework_postgres.py --pg-bin "$TEST_PG_BIN" \
  --major "$TEST_PG_MAJOR" --settings config.settings.campaign_review -- \
  python manage.py test \
  tests.v14_security_review.test_search_boundary.SearchProjectionBoundary --verbosity 2
```

Local binaries: `/tmp/v9-pg/usr/lib/postgresql/17/bin` (17.12 Debian build),
`/tmp/v12-pg18-built/bin` (18.7 local build). Fresh isolated owned clusters; no
claim of identical packaging to hosted CI. Test setup uses the existing legacy
fixture bootstrap only; strict enforcement is explicitly enabled for all
reproducer search calls.

## V14 review queue — threats and integration requirements

These are planned boundaries, not unexecuted PASS claims. Each future execution
must identify its exact product SHA and the changed code it tests.

| Surface | Independent challenge / required invariant | State |
| --- | --- | --- |
| Batched rights | Exact case, identity epoch, edition/archive/input/hash, use and expiry; no cache reuse across scopes; deny missing/duplicate grants; early-row revocation during later callback | SEC14-01 reproduced; V14 implementation pending |
| Search/pagination | Filter/revalidate before titles, facets, counts, cursor/next-page hints; empty-result responses must not disclose denied candidates; expiry while building later result; document snapshot/serialization boundary | Pending actual V14 API |
| Human evaluation | Explicit independent reviewer and exact dataset/query/ranker revision; no fabricated human gold, promotion of PENDING or evaluation text disclosure; preserve TOC/full-text distinction | Pending actual V14 API |
| PDF/audio | Case scope and Evidence/revision at final bytes boundary; exact media hash/source version; withdrawn rights and timed locator checks; no implicit conversion to text or content sniffing grant; CSP, microphone explicit acceptance and resource release | Pending changed routes; local protected microphone remains NOT_RUN historically |
| Classification/publication | Classification approval cannot grant publication; independent publication approval, original source rights and exact current Evidence; withdrawal redacts metadata/count/category without erasing history | Pending changed publication contract |
| Maintenance | New reads that write, budgets, copies, admin and callbacks require admission; FROZEN denies writes; retain admission through transaction/on_commit; rollback failure cannot authorize resume | Pending changed entrypoint inventory |
| Restore | Strict encrypted-only capture; wrong key/hash reject before target; preserve new schema/guards/assets/permissions and source FROZEN; tamper rejects before READY; unknown identity retains quarantine; SEC13 quoted-data distinction | Pending migrations/manifest changes; SEC13 bounded PASS remains pinned to its old reviewed head |

For concurrent rights tests, use separate DB connections and explicit barriers
once the changed batch/lock contract is available; callback mutation, clock
expiry, and committed concurrent DB revocation are different evidence classes.
Do not call one a proof of the others. Avoid sleeps as a substitute for proving
that a contender reached its mutation boundary.

Handoff: import the owned reviewer commit, repair SEC14-01 in the implementing
lane, then provide exact lane/integration heads and relevant contracts. Shared
CI/route/settings changes belong to the integrator. This report will receive
append-only execution/disposition history at each reviewed repair head; original
failures will not be relabeled PASS. Product files and GitHub settings remain
untouched by this lane.

No new engineering percentage, formal acceptance, real data/keys, external send,
production, main merge, U03 permission or automated fatwa approval. Gate B
NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
