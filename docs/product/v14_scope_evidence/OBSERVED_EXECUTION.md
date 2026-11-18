# V14 — bounded evidence bridge (post-handoff continuation)

This is a **read-only evidence/verification change**, not V15, not a deployment,
and not a change to the V14 runtime. It starts from Draft PR
[#233](https://github.com/sami77337/fatwa-platform/pull/233) at
`6b4f77e29ccb1f21d48ad3d77f5e63d3be953fab`.

## What was actually added

- `observed_execution.json` cross-references **11 existing owner points** in four
  existing V14 candidate groups to source files, 14 distinct named positive or
  negative test methods, and two decoded exact-head GitHub Actions job logs:
  PostgreSQL 17 job `134656248871` and PostgreSQL 18 job `134656248333`.
- Each source/test file is pinned to its **Git blob SHA-1**. This is distinct from
  a raw file SHA-256; the offline verifier recomputes the Git object identity.
- `verify_observed_execution.py` rejects mismatched owner text/classifications,
  missing original candidate mappings, stale/forged test-method references,
  missing PG majors, wrong job IDs/heads, changed Git blobs and acceptance
  inflation.
- `test_observed_execution.py` supplies nine focused positive/negative tests.

A manually checked GitHub Actions log is evidence of a previously executed test,
**not** proof that the original owner accepted the requirement. The stored test
lines are bounded observations; GitHub log authentication is not cryptographically
reproduced by this offline verifier.

## Local, read-only verification

Run from a checkout containing the V14 parent Git commit:

```sh
python docs/product/v14_scope_evidence/verify_observed_execution.py --check
python -m unittest discover -s docs/product/v14_scope_evidence -p 'test_observed_execution.py' -v
```

The commands use only Python's standard library and local Git objects. They do
not need Django, PostgreSQL, Chrome, an external network, real data or Codex.

The data documents past **V14** tests. These commands do **not** rerun the product
and are not a substitute for a fresh browser or security test.

## Boundaries preserved

- No edits to `matrix.json`, `matrix.csv`, `build.py`, the historical
  `evidence.json` or the 556 original point classifications.
- The existing V14 matrix correctly remains **303 PARTIAL, 52 DECISION,
  168 NOT_IMPLEMENTED by available evidence, 33 OUT_OF_SCOPE, 0 COMPLETE**.
- Recorded observations for 11 original points are **not** completed/accepted
  points. The V14 runtime evidence scaffold remains PENDING.
- PDF plug-in selected-page rendering remains **NOT_VERIFIED**; ranking requires
  independent human review; source 622 is a TOC; U03, real channel transport,
  production identity, production storage and wider operational security remain
  unresolved.
- Gate B `NOT_PASSED`; C/D/E `HOLD`; Phase01 `BLOCKED`;
  `NOT_DEPLOYED`. No merge to `main`, no external delivery, real-user data,
  automatic fatwa approval, permission expansion or GitHub settings change.

The next substantive acceptance step would require point-specific owner-reviewed
criteria and independent evidence, not merely retagging this file.
