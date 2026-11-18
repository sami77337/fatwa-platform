# V12 recovery P0 evidence

Base verified through PR #230 metadata and remote branch:
`5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`.
Branch `codex/20261117-v12-recovery`; V11 branch/history preserved.
No P1 work, subordinate PR, main merge, GitHub configuration change or deployment.

## Affected PostgreSQL matrix — PASS

Runtime: Python 3.13.5, repository-pinned dependencies, including existing Fernet
implementation from cryptography 50.0.2. Disposable synthetic clusters only.

| Runtime | Result | Duration |
| --- | --- | --- |
| PostgreSQL 17.12, Debian binary | **8/8 PASS** | 5.715s |
| PostgreSQL 18.7, local source build | **8/8 PASS** | 5.313s |

These are the same eight tests on two database majors, not sixteen distinct
functional requirements. No unmodified V9/V10/V11 suite was rerun.

Both runs reported:

```text
V12_STRICT_BASELINE {"algorithm": "Fernet", "external_objects": 2, "state": "VERIFIED", "tables": 56}
Ran 8 tests
OK
```

Actual commands, from `/workspace/fatwa-platform`:

```sh
/workspace/fatwa-venv/bin/python -m infra.dev.with_casework_postgres \
  --pg-bin /workspace/pg/usr/lib/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  /workspace/fatwa-venv/bin/python -m apps.platform_recovery.v12_recovery_tests \
  --pg-bin /workspace/pg/usr/lib/postgresql/17/bin

/workspace/fatwa-venv/bin/python -m infra.dev.with_casework_postgres \
  --pg-bin /workspace/pg18-local/bin --major 18 \
  --settings config.settings.campaign_review -- \
  /workspace/fatwa-venv/bin/python -m apps.platform_recovery.v12_recovery_tests \
  --pg-bin /workspace/pg18-local/bin
```

Coverage in `v12_recovery_tests.py`:

1. Plaintext API and `legacy-snapshot` CLI are denied before any dump, adapter
   initialization or artifact creation. Default strict, explicit strict, ordinary
   profile flag downgrades and non-boolean values are checked.
2. Only a separate process selecting the exact V10 test settings can create and
   restore a legacy bundle. Its restored services/bytes/permissions/schema work.
   The ordinary strict profile refuses that same artifact before target creation;
   strict=True also wins inside the compatibility profile.
3. Strict encrypted roundtrip restores 56 tables and two unique private originals,
   retaining the existing case/evidence/answer/release relationships. A fresh
   application process verifies exact attachment/audio bytes, retained revisions,
   authorization denials, missing-authority denial, immutable SQL protections and
   stale-answer closure after new facts. Source row baseline remains unchanged.
4. Wrong valid key, malformed/short/missing key and malformed/wrong hash create
   neither a new database nor target directory.
5. Ciphertext tampering/truncation with a **recomputed outer hash** still fails
   Fernet authentication before target creation.
6. Correctly authenticated but missing/corrupt originals, changed inner manifest,
   malformed envelope/files structure and an extra plaintext package file fail
   before creating a target. Existing object requirements are not weakened.
7. Repository/artifact/symlink key boundaries remain closed, including a simulated
   repository under `/tmp`; the simulation does not copy a real key into the repo.
8. Invalid-key CLI output is only a fixed failure code: no key path, key bytes,
   source capability, SQL, payload or traceback; no target is created.

The encrypted package inventory is exactly `backup.fernet` and `COMPLETE`.
No new plaintext dump/manifest staging appears on the strict path. The deliberately
isolated V10 compatibility test creates its old plaintext fixture only under the
separate test settings and its owned temporary root; it is not V11/V12 output.
Keys live in a different temporary key directory and are never committed/uploaded.

Reopened-process assertions also run Django system checks and migration drift.
Ruff and staged whitespace checks passed for the changed/owned files. No model,
migration, dependency pin or shared configuration was changed.

## Environment preparation

PG17.12 was already available in the workspace. The downloaded PG18.7 Debian
binary required newer system libraries, so it was not used and no system library
was replaced. PG18.7's source archive from the Debian mirror was built/installed
entirely under `/workspace/pg18-local`; build tools were also extracted locally.
The initial build needed an explicit path to the local m4 executable; after that
correction it completed and reported `postgres (PostgreSQL) 18.7`. Both servers
ran through the existing disposable-cluster helper. No runtime test failure was
reclassified as a pass and no host security setting was changed.

## Delivery boundary and remaining integration

See [v12_recovery_contract.md](v12_recovery_contract.md) for the proposed strict
settings and the dedicated test-profile identity requirement.

The integrator owns shared setting/CI updates and legacy fixture adaptation:
existing V10 tests and V11's legacy fixture bootstrap must use an isolated
compatibility composition or be adapted; do not lower V11/V12 runtime protection.
The tree currently uses `integration.py` and `middleware.py` alongside maintenance;
there is no standalone `admission.py`. None of those files is modified here.

No P0 aggregate merge/browser/CI result is claimed by this lane. P1 must wait for
integration, passing affected checks and a recorded result. Unknown pre-nonce
target behavior, maintenance admission and source/asset schema rules remain
unchanged; no unknown target was adopted or deleted by this change.

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
No real data/keys, external sending, U03 grant, automated religious approval or
assumed Meta contract. Leadership reference **79% ±8** is unchanged, not acceptance.
