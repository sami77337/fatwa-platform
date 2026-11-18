# V13 schema restore regression

Base: `cd8e221` on the V13 integration line. Scope: recovery schema canonicalization
and focused regression tests only. No gate, production, key, permission or GitHub
configuration change. Strict encryption, immutable assets, ownership, quarantine
and complete schema/row/reference checks remain enabled.

## Observed failure and cause

V10, V11 and V12 CI on `908b17b` failed with
`restore_failed_target_quarantined:restored_schema_mismatch` on both PostgreSQL
majors. Historical job IDs supplied by the integrator:

- V10: PG17 `134509183098`; PG18 `134509182866`.
- V11: PG17 `134509183763`; PG18 `134509183259`.
- V12: PG17 `134509182758`; PG18 `134509182976`.

A fresh PG17.12 reproduction of
`MaintenanceIntegrationTests.test_encrypted_restore_writes_only_proven_new_target_while_source_frozen`
failed identically before the fix. Comparing the complete source and restored
schema dumps showed exactly one differing line: `classification_one_decision`.
PostgreSQL changed the partial unique index predicate's varchar literal-array
cast from `(ARRAY['APPROVE'::character varying, 'REJECT'::character varying])::text[]`
to `ARRAY[('APPROVE'::character varying)::text, ('REJECT'::character varying)::text]`.
No missing table, trigger, function, constraint or row was observed in that diff.

The existing canonicalizer already handled this exact deparser equivalence in
CHECK constraints. It now also handles single-line partial index definitions.
Values, value order, names, uniqueness, column and predicate remain fingerprinted.
Dollar-quoted function bodies are retained verbatim, including text resembling
index definitions or normalizer directives. No schema check is omitted.

## Focused execution

Fresh synthetic PostgreSQL17.12 and18.7, using the existing isolated-cluster helper.
Per major:

- Four new tests PASS, then the additional real-index-tampering test PASS: five
  distinct tests in `tests.casework.test_v13_recovery_schema`.
- The encrypted/FROZEN roundtrip compares complete source and restored canonical
  schema bytes and explicitly requires the four classification/timed-citation
  tables, their functions/triggers/constraints and the partial unique index.
- Changing UNIQUE to nonunique on the actual restored index is detected as
  `restored_schema_mismatch`; the proven newly-created database is rolled back.
- Isolated V10 compatibility: three existing tests PASS — complete restore and
  reopened permissions, actual schema-tamper rejection, and independent-server
  restore. The V10-only settings module is used explicitly for these tests; strict
  V11/V13 encryption defaults are not changed.
- Ruff and whitespace checks PASS.

The initial failing reproduction is retained in `/tmp/v13-schema-repro.log`.
Successful local logs are `/tmp/v13-schema-pg17.log`, `-pg18.log`,
`/tmp/v13-schema-tamper-pg17.log`, `-pg18.log`, and
`/tmp/v13-schema-v10-pg17.log`, `-pg18.log`. These are local execution evidence,
not claims of hosted CI on a later integrator SHA. Unaffected product/browser
suites were not rerun here. Final combined CI and the protected browser remain
with the integrator.
