# V13 complementary integration security review

**Bounded PASS after two fixes.** This reviewer did not implement product code.
The dedicated external V13 application review in `V13_REVIEW.md` remains **PENDING
for V13** from this reviewer's perspective. This document neither replaces its
verdict nor reclassifies its historical V12-delta PASS. No acceptance, production
approval, or percentage change follows from this result.

Initial exact product: `1ea53ead8e6166a64b766968efbb63ea00f4c7c1`, compared with
`5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`. Final inspected product:
`4f71d2eed870599791bfea72005ddcd37295f619`, incorporating the first fix
`8eb1d76e25dcfd999efc8f5b5be8cc2f2a118adc`.

Ownership: only `tests/v13_integration_security/**` and this report, on isolated
`codex/20261118-v13-integration-security`. Product fixes were implemented by the
integrator, then merged into this worktree for independent verification.
AGENTS.md, source-scope trace, browser-audio and timed-citation contracts were read.
There is no `.agents/skills` directory in this worktree.

## Findings and preserved failure history

1. **BLOCKER on initial product, reproduced on PG17.12 and PG18.7.**
   `casework.services._answer_timed` invoked `grant_deadline` again after
   `timed_citations.services.for_locked_answer` completed its final authority
   checks. A real configured identity-directory revocation during this additional
   callback allowed `answer_media.staff_read` to return private audio bytes.
   Revoking the policy's READ_MEDIA/CITE grants during the last redundant CITE
   callback likewise allowed `answer_media.requester_read` to return bytes.
   Both tests required `CaseConflict` and failed. They changed only synthetic
   authorities in the already-held canonical case lock; no external SQL or
   unrelated principal was used. Exact original tests are preserved by commits
   `c9b8adb` and `6ec9dc8`; logs are `initial_pg17.txt` / `initial_pg18.txt`.
2. **First fix insufficient, independently reproduced on PG17.12.**
   `8eb1d76` removed all post-validation policy calls by collecting deadlines from
   the existing projection guard. Identity revocation at the last retained
   callback was correctly denied. However, revoking CITE/READ_MEDIA during the
   final retained CITE callback in `_rights`, immediately before its genuine
   previously obtained deadline returned, still allowed requester bytes. The
   unchanged negative expectation failed in `first_fix_pg17.txt`. PG18 was not
   rerun at this intermediate product revision.
3. **Second fix independently verified.**
   `4f71d2e` rechecks both permits after both deadline callbacks, while retaining
   final identity and expiry checks. No further deadline callbacks are introduced.
   The final tests keep the late attack, assert it actually executed, and require
   `CaseConflict`; they do not move it earlier or accept leaked bytes. Separate
   coverage requires zero grant-deadline calls after the validated hook returns.

The initial same-identity requester probe was denied by the existing release
identity recheck, and attempting a distinct private releaser was already rejected
by `private_release_approver_changed`; neither was reported as a product leak.
Early test instrumentation/discovery was corrected: importing a TestCase directly
accidentally collected existing tests, and package-label discovery hit the repo's
namespace-package limitation before execution. Final module labels below run only
this review's seven tests. No timeout, skip, or authorization relaxation was used.

## Review coverage and limits

| Shared integration area | Evidence / conclusion |
|---|---|
| Initial audio intake | New focused HTTP test fails the owner-row INSERT **after** the private blob was written. No case/source/evidence/attachment/tracking capability survives; the unreferenced UUID is inaccessible, and retry reuses the same immutable blob inode. Cross-requester same-event replay is rejected; owner replay issues no second token. |
| Timed canonical/downstream use | Five focused tests cover staff/requester final-callback revocation, original audio/inspect denial, no callbacks after final validation, and expiry after actual bytes were assembled. Missing-app table detection and approval/publication hooks were inspected; their existing suites were not claimed as new independent executions. |
| Recorder assets, CSP, routes | Static review of exact GET/HEAD assets, loopback route guard, UUID timed routes, scoped dispatcher, escaped templates, native multipart fields and recorder-only HTML policy. Byte responses retain their existing sandbox CSP; no remote origin or arbitrary asset path added. Real microphone/sandbox browser execution was **not run by this reviewer**. |
| Classification case frame | Static review: authorized server case reference must match action family and cannot conflict with other resolved references; client case input does not become authority. Existing source/app approval services remain authoritative. |
| Measured search state | Static review: signed browser/identity/case/version-bound state preserves exact filters/ranking; unknown ranking and unavailable strict mode fail closed; source opens and citation changes keep their own authorization. No semantic/human-review claim inferred. |
| Recovery schema canonicalization | Static review of top-level CHECK/partial-index literal normalization and dollar-quoted body tracking. Values/order/names/predicates remain material; function source is not intentionally normalized. No independent encrypted restore or schema-tamper drill was run here; integrator recovery evidence remains separate. |

This is not exhaustive review of every app, arbitrary privileged SQL, a malicious
Python policy implementation, deployment, or external identity infrastructure.
The grant contract still requires revocation to serialize with the canonical
case lock. No statement of general linearizability outside that contract is made.

## Focused execution evidence

| Product / test content | PG17.12 | PG18.7 |
|---|---|---|
| Initial `1ea53ea`, original 2 reproductions | **2 FAIL** | **2 FAIL** |
| First fix `8eb1d76`, retained 2 probes | 1 PASS / **1 FAIL** | NOT RUN |
| Final product `4f71d2e`, test content `a4183c579801ff71253e647819609032922cc3bf` | **7 PASS** | **7 PASS** |
| Explicit attack-executed assertions `3f5f5ce9d9ea2ca9ffb473630097a6cd2e4d52ea` | **2 affected PASS** | **2 affected PASS** |

PG17's seven-test run used the exact test content subsequently committed as
`a4183c5`; PG18 ran that committed head. Both have the same product tree as
`4f71d2e`. The follow-up changed only two assertions and reran those two tests on
both majors. Evidence/report-only commits after these runs do not claim a fresh
product execution. Ruff and `git diff --check` passed for reviewer-owned changes.

Run (fresh owned synthetic cluster; choose the installed matching PG binary path):

```sh
python infra/dev/with_casework_postgres.py --pg-bin "$TEST_PG_BIN" --major 17 \
  --settings config.settings.campaign_review -- python manage.py test \
  tests.v13_integration_security.test_boundaries \
  tests.v13_integration_security.test_intake --noinput --verbosity 2
```

Use `--major 18` with PG18 binaries for the second supported major. Stored stdout
and SHA-256 manifest are under `tests/v13_integration_security/evidence/`.
No full unrelated suite, remote CI, browser, or post-cherry-pick campaign result
is attributed to this reviewer. The integrator must retain final-head CI and the
external designated V13 review as separate evidence.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**; **NOT_DEPLOYED**.
No real data/audio/keys, external delivery, main merge, GitHub setting change,
U03 permission, automated scholarly approval, or inferred rights were introduced.

## Supplemental static review of the four new applications

Requested while hosted verification was running; inspected target
`09cc55aa021660f593bb1b70e850d0f448ddad3a`. Its `apps/`, `config/` and `templates/`
product delta from repaired `4f71d2e` is empty. A path-limited comparison also
confirmed that the four applications and reused authority/admission services in
this review worktree are identical to that exact target. The V12-to-V13 product
delta includes these new applications; this supplement expands the earlier
shared-integration review rather than treating their implementation tests as an
independent rerun.

**Outcome: no additional concrete security blocker established by this static
review.** This is a bounded source inspection, not comprehensive clearance.
The external designated V13 application review remains **PENDING**; this reviewer
has only received its separate historical baseline review, not its V13 verdict.
The dynamic tests and failure history above remain attributed to their original
heads. No existing test, browser, or hosted CI suite was rerun for this supplement.

| Newly inspected source scope | Security observations |
|---|---|
| `browser_audio/assets.py`, `context.py`, `capture.html`, `capture.js`, `worklet.js` | Fixed local asset map, synthetic feature gates and exact methods; no client-selected filesystem path. Microphone request occurs on explicit start, no initialization capture/device enumeration. Epoch checks dispose late permission results; cancel, pagehide, hidden-page, device-ended and worklet-error paths release tracks/context. Preview bytes become the native input only after acceptance; capture adds no network upload/ASR or server permission. Worklet limits frames, WAV is bounded PCM, and output is silent. Native server validation remains mandatory. No unsafe HTML sink or external send was found in these inspected client files. Browser timing/device compatibility is not established by static inspection. |
| `timed_citations/services.py`, `rights.py`, `views.py`, `guard.py`, models and both migrations | Canonical scoped case lock, exact immutable owner/source/version/hash/metadata/duration pins, mandatory READ_MEDIA plus CITE with aware deadlines, repaired post-callback checks and final identity checks. UUIDs do not act as capabilities. Mutation forms retain CSRF and server identities; audio routes resolve current scoped identity and recompute source eligibility. Proposal/confirmation require the current unreviewed answer; corrected history is append-only, old references are not auto-cloned, withdrawal remains possible without source readability. PostgreSQL guards bind lineage/owner/case/answer and reject conflicting history changes. Public entry services carry mutation admission; the internal `for_locked_answer` hook still relies on its documented caller-owned canonical lock. |
| `arabic_search_eval/services.py`, `ranking.py`, `evaluation.py` | Ranking runs over an already authorized bounded reference window. Strict source-rights mode and the existing case/workspace gates are mandatory; candidate source opens and selected-result DISCOVER/read checks surround ranking, with final actor and enclosing source-expiry checks. Query/token/window/type bounds are explicit; no dynamic SQL/network/content generation is introduced. Returned coverage remains a bounded window, book-622 material is TOC metadata, and human review remains PENDING. The fixture evaluation oracle is not an authorization implementation or proof of real corpus relevance. |
| `classification_review/authority.py`, `services.py`, `views.py`, models, SQL guards and template | Explicit per-action authority supplements current case/publication/knowledge/source checks. Approval/rejection requires a different provider/subject from the proposer, and append-only DB guards enforce decision/lineage conflicts. Source verification is current, exact and rights-aware; ordinary desks are enclosed by the inherited projection-expiry guard. Audit/withdrawal paths omit labels/reasons/source details/decision text and do not confer availability. Mutations use existing admission and transaction scopes, with final authority/identity rechecks. UI state is advisory only: no canonical publication category or knowledge relationship is automatically mutated. Escaped native CSRF forms accept no client-supplied actor. |

The supplementary reads included the reused `knowledge_links._edition` /
`_withdrawal_edition` scopes, `case_citations._projection_expiry_guard`, strict
research-rights adapter boundary, request-bound directory and maintenance
`mutation_service`. They support the limited observations above; they do not
establish protection from privileged SQL, arbitrary malicious Python authority
implementations, unreviewed production configuration, or every possible
concurrency interleaving. No new reproduction was added because this inspection
did not establish a new concrete concern requiring an experiment.
