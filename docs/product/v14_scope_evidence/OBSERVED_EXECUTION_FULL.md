# Full bounded V14 candidate observation

This addendum extends the prior 11-point bridge to all five candidate groups in
`candidates.json`. It records 24 group occurrences covering 22 unique owner
point IDs, with the repeated occurrences of points 408 and 554 retained because
they appear in more than one bounded candidate group.

For each group, the receipt stores the candidate's original point text and
preserved classification, group-specific bounded relevance, code/test Git blob
SHA-1 pins from the V14 product-tested commit, and 20 distinct named positive
or negative test methods. The passing unittest output lines were directly
observed in the exact-head PG17 and PG18 GitHub Actions job logs.

The verifier deliberately reads candidate definitions from the original V14
source SHA and code/test blobs from the exact V14 tested product SHA. These
are different provenance roles and must not be conflated.

Run from a checkout containing both commits:

```sh
python docs/product/v14_scope_evidence/verify_observed_execution_full.py --check
python -m unittest discover -s docs/product/v14_scope_evidence -p 'test_observed_execution_full.py' -v
```

The V14 CI workflow runs both commands on PostgreSQL 17 and 18. The verifier
does not re-run the product or independently authenticate GitHub's logs; it
checks consistency of the bounded receipt, exact source point mappings,
source/test blob identities, method inventories, and recorded run attribution.

## Non-acceptance limits

- No owner point status changes; no COMPLETE credit is awarded.
- Repeated owner point IDs are accepted only if original owner text and
  preserved classification agree; group-specific relevance text may differ.
- The original matrix counts remain unchanged.
- A passing CI line is not owner acceptance or an independent security review.
- The historical browser startup failure remains recorded with unknown root
  cause.
- Chrome's original PDF viewer page positioning remains NOT_VERIFIED; the
  one-page derivative is a distinct private artifact.
- Search relevance, source rights, U03 permissions and production readiness
  remain unresolved.

Gate B `NOT_PASSED`; C/D/E `HOLD`; Phase01 `BLOCKED`;
`NOT_DEPLOYED`. No main merge, deployment, external send, real user data,
permission expansion or automatic fatwa approval.
