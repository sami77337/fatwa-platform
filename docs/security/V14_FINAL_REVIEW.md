# Independent V14 repair review

Candidate: e8b1617a6f03ca3ad42b946d9592aa524daf0d3e, Draft PR #233.

## Scope and security judgment

SEC14-02/03: PASS within the tested final-callback/final-epoch model on product head 7d03f14561bc9612a1e7588c3b4a706170313063. This is not a general security certification or product acceptance. Exact candidate CI confirmation is recorded below.

Reviewed evaluation propose/decide/history projection before the final authority callback and current identity re-resolution after it, inside transaction.atomic. Reviewed media deadline enrollment and final clock after the last policy epoch, also inside case transaction. Default strict deadlines remain; library-preview alone retains its existing emitted-result deadline tracking with final post-epoch clock. This preserves filtering of expired candidates without disclosing them, while direct media operations remain strict. No permission cache or callback retry was added.

Independent runtime evidence read from hosted job logs at 7d03f14:
- V14 PG17 job 134646747935 and PG18 log: 124 tests each, original four SEC14-02/03 reproductions pass, ten independently added identity/metadata/review/rollback attacks pass, schema restore test passes.
- V13 PG17 job 134646748036 and PG18 log: 120 tests each; collection timed-expiry regression passes.
- V14 browser proof on each major: sandbox=true, no external requests or page errors, widths 320/1280, encrypted independent-target restore READY/target_http PASS, wrong key/hash DENIED, source unchanged and frozen. PDF plugin selected page remains NOT_VERIFIED.

Connected GitHub compare 7d03f14..e8b1617 confirms exactly two changed files: tests/casework/test_v7_browser.py and docs/security/V14_LOCAL_REPAIR.md. No product code differs. Reviewed the test change: identical width assertions, readiness of the same-origin CSS, initial-state and bounded failure diagnostics, no larger timeout/retry/sandbox relaxation.

## Preserved failures and limitations

The first repair f1eed92 failed the V13 collection filter test and was corrected in product code, not by weakening that test. At 7d03f14 V7 run 44258774857 observed 509>320 after 34 functional tests passed; cause remains ROOT_CAUSE_UNKNOWN because no identifying DOM/trace was available. A later readiness-test success cannot retroactively prove the cause or rule out transient pre-CSS overflow.

Reviewer-local PostgreSQL and protected browser execution NOT_RUN due environment limits. Runtime evidence above is hosted, read independently, not claimed as local execution. Tests use synthetic identities and time/callback adversaries, not proof against arbitrary privileged SQL or all concurrent races. Human ranking review PENDING, source provenance caveats unchanged, PDF selected page NOT_VERIFIED. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No acceptance percentage, production authorization, main merge, or V15.

## Final candidate workflow status

Confirmed via connected GitHub API: all 17 PR-triggered workflows completed at e8b1617, 16 SUCCESS and FAST9 FAILURE. No all-green claim.

Candidate update: e8b1617 V7 run 44260132833 completed SUCCESS. Read PG17 job 134651167874: 34 functional tests passed; initial CSS absent for cited-answer/library but present for attachment. This validates the readiness-contract risk, not the historical attachment-overflow cause. FAST9 run 44260132958 failed browser_startup at unchanged 10000 ms; observed elapsed 10009 ms, launch marker/child launched observed, launch did not return, exit/sandbox/loader markers UNKNOWN. ROOT_CAUSE_UNKNOWN; no rerun, larger timeout or sandbox weakening requested. FAST9 proof records d501af3eaea9ad4f81110b17dfc634298674a4ca (PR merge context), so do not mislabel its emitted SHA as e8b1617. Current head is not all-green.


## Final independent decision

**PASS, narrowly scoped to SEC14-02 and SEC14-03 on e8b1617a6f03ca3ad42b946d9592aa524daf0d3e.** Independently read exact-head V14 PG17 job 134651168331 (direct GitHub logs) and PG18 job 134651168060: 124 tests each, all original four and all additional ten challenges PASS, plus schema restore. Both protected browser proofs identify the exact candidate and report sandbox=true, encrypted restore READY, target_http PASS, wrong key/hash DENIED, source frozen/unchanged, no external requests or page errors. V13 run 44260133009 succeeded, 120 tests per major including the collection filter regression.

V14 run: https://github.com/sami77337/fatwa-platform/actions/runs/44260132831
V13 run: https://github.com/sami77337/fatwa-platform/actions/runs/44260133009
V7 run: https://github.com/sami77337/fatwa-platform/actions/runs/44260132833
Preserved FAST9 failure: https://github.com/sami77337/fatwa-platform/actions/runs/44260132958

Overall campaign CI is NOT all-green. FAST9 startup remains unresolved/ROOT_CAUSE_UNKNOWN; this does not overturn the separately reproduced security boundary results, nor does the security PASS constitute general acceptance. No further changes or reruns recommended merely to hide that failure. Deliver V14 with these limitations, then stop as directed.
