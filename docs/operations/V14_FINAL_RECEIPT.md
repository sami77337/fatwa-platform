# V14 bounded final receipt

Runtime-verified product/test SHA: `e8b1617a6f03ca3ad42b946d9592aa524daf0d3e`.
Draft PR #233 remains based on V13, not main. Any later receipt-only commit is
not a new runtime execution. No main merge, production, real data or V15.

## Verified runtime and independent review

- [V14 run 44260132831](https://github.com/sami77337/fatwa-platform/actions/runs/44260132831): PG17 job 134651168331 / PG18 job 134651168060, 124 affected tests per major, 25 scope checks and 12 startup checks. Original four SEC14-02/03 attacks, ten independent additional attacks and schema recovery pass.
- Both connected Chrome journeys identify the runtime SHA, sandbox=true, widths 320/1280, zero external requests/page errors, independent encrypted restored target READY/target_http PASS, wrong key/hash DENIED, unchanged/frozen source.
- [V13 run 44260133009](https://github.com/sami77337/fatwa-platform/actions/runs/44260133009): 120 tests per major and connected recovery journey pass, including unchanged collection-expiry regression.
- [V7 run 44260132833](https://github.com/sami77337/fatwa-platform/actions/runs/44260132833): 34 functional tests and protected PG17 browser pass. Layout is asserted after CSS readiness. This does not establish the cause of the earlier 509px overflow or exclude transient pre-CSS overflow.
- [Independent final review](../security/V14_FINAL_REVIEW.md): limited PASS for SEC14-02/03, not general certification or acceptance. Original blocked report and failure artifacts remain intact.

## CI failure retained

17 pull-request runs: 16 success, 1 failure; three push runs success, hence 19/20
associated runs, not all-green. [FAST9 run 44260132958](https://github.com/sami77337/fatwa-platform/actions/runs/44260132958)
failed protected browser startup at the unchanged 10000 ms bound, elapsed 10009 ms.
Launch and child-launched markers were observed, launch did not return; exit,
loader and sandbox-cause signals UNKNOWN. ROOT_CAUSE_UNKNOWN. Its emitted proof
SHA is `d501af3eaea9ad4f81110b17dfc634298674a4ca` in the PR merge-checkout
context, not the runtime product SHA above. No retry, timeout increase or sandbox
relaxation was performed. Historical B6/D6/FAST9 failures are not erased.

## P2 reconciliation without unsupported row credit

The [556-point trace](../product/v14_scope_evidence/README.md) remains unchanged:
303 PARTIAL, 52 DECISION, 168 NOT_IMPLEMENTED, 33 OUT_OF_SCOPE, 0 COMPLETE;
zero new status upgrades and no new percentage. Its machine-readable evidence
scaffold still reports PENDING_INTEGRATED_RUNTIME_EVIDENCE and zero verified V14
points: this receipt is campaign-level execution evidence, not a reviewed
point/SPEC/file/symbol/positive-and-negative-test binding for every row.
Do not infer that no V14 runtime ran from the old scaffold wording, or that this
receipt completes all 556 requirements. Per-point evidence promotion is a
remaining documentation gap; no validator was weakened to add unsupported credit.

The DOCX provenance receipt is parent-local attestation, not independent Cloud
original-byte verification. XLSX remains derivative. Historical workbook
conversion/authorship and 17 UTC serialization differences remain unresolved.
No source binary was uploaded. 622 denotes one book TOC, not general taxonomy.

## Remaining limits and stop

Human ranking review PENDING; PDF engine-selected page NOT_VERIFIED; classification
publication policy closed simulation; no production KMS/PITR or privileged external
SQL guarantee; unknown restore identities require manual quarantine. Private media
rights do not authorize public files. Local PG/browser runtime was unavailable;
hosted evidence was read independently. Gate B NOT_PASSED; C/D/E HOLD;
Phase01 BLOCKED; NOT_DEPLOYED. V14 delivered with limitations, then stop.
