# V14 independent security review — baseline SEC14-01 BLOCKED

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
