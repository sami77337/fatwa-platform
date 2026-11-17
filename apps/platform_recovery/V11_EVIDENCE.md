# V11 E validation receipt

Base verified: PR #229 head and remote branch
`0f90bb4f6c4ba426055fc77a3a783c2061d6ee19`.
Only `apps/platform_recovery/**` changed on `codex/20261117-v11-recovery`.
V10 branch remains intact; no subordinate PR, main merge, deployment or external send.

Runtime: Python 3.13.5, repository-pinned dependencies including cryptography 50.0.2,
PostgreSQL 17.12 Debian, disposable loopback synthetic clusters. No real data/key.

## Final new functionality — PASS 16/16

Actual command from `/workspace/fatwa-platform`:

```sh
/workspace/fatwa-venv/bin/python -m infra.dev.with_casework_postgres \
  --pg-bin /workspace/pg/usr/lib/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  /workspace/fatwa-venv/bin/python -m apps.platform_recovery.tests_v11 \
  --pg-bin /workspace/pg/usr/lib/postgresql/17/bin
```

```text
SYNTHETIC_POSTGRES=postgres (PostgreSQL) 17.12 (Debian 17.12-0+deb13u1); fresh owned cluster
RECOVERY_BASELINE:
  tables=51; filesystem_objects=2; media_owner_references=5
  cases=2; evidence_rows=3; answer_revisions=2; attachments=1; private_releases=1
Ran 16 tests in 11.156s
OK
```

Covered by `tests_v11.py`:

- Full encrypted capture/restore, reopened service process, exact original bytes,
  retained answer revisions, schema/ownership protections, private-release checks,
  cross-case/organizer/missing-authority denials, stale-answer closure after facts.
- A second newly initialized PostgreSQL **server**, not only another database:
  authenticated restore and the same reopened-process service checks passed.
- No plaintext archive staging on encrypted capture/restore; sealed directory has
  only ciphertext and COMPLETE. Key is not present in ciphertext or artifact output.
- Wrong key, truncated/modified token with recomputed outer pin (proves Fernet
  authentication, not just SHA checking), missing/corrupt decrypted asset and
  unexpected traversal path fail before target creation.
- Real child-process writer admitted before DRAINING finishes its case write;
  new WRITE and GC entrants are denied, then FROZEN is reached. Backup cannot race
  explicit resume. Nested synchronous service guards work through a transaction.
- `os._exit(73)` during ciphertext publication leaves only incomplete ciphertext
  and a durable FROZEN gate. Explicit generation-bound resume is required.
- `os._exit(73)` after a database nonce comment but before OID journaling produces
  a nonce-provable quarantine. Stale/unconfirmed reconciliation is rejected;
  explicit matching inspection records identity and permits verified rollback.
- Death before nonce creation leaves an unknown target; reconciliation/rollback
  refuse it. Missing/null nonce with an otherwise matching OID is also rejected.
- Another process observes BUSY while restore owns the target; it cannot reconcile
  or drop an active restore. Expired/copied execution contexts cannot bypass locks.
- Failed encrypted restore preserves source, verified backup and target files;
  only the owned database is rolled back. Fresh retry succeeds.
- Metadata-only CLI status exposes no key path, capability, manifest or payload.
  An artifact-path key attempt uses a non-key placeholder and is rejected before
  reading it. All actual synthetic keys remain in a separate temporary directory.
- Missing configuration, changed database binding, stale generation and unfrozen
  backup all fail closed.

The harmless negative key-location fixture was subsequently changed to a literal
non-key placeholder, avoiding even a temporary real key in the artifact tree;
that affected test was rerun separately. Source implementation did not change.

## Affected V10 compatibility — PASS

The capture/restore I/O refactor initially passed **22/22** existing recovery tests
in **17.664s**, including READY publication/fsync faults added by V10 integration.
No unrelated V10/V9 product suite was run.

After execution-lease and strict nonce hardening, **8/8** affected legacy cases
passed in **13.753s** on a fresh independent cluster:

```text
test_01_complete_restore_and_reopened_service_permissions
test_08_rollback_pending_if_consumer_connected_then_retry
test_09_wrong_rollback_identity_is_not_dropped
test_10_hard_process_crash_is_quarantined_then_recovered
test_16_fresh_independent_cluster_restore
test_20_failed_ready_publication_records_failure_and_rolls_back
test_21_persistent_ready_journal_failure_keeps_nonready_identity
test_22_failed_ready_directory_sync_preserves_target_for_safe_retry
```

Run them by appending these `RecoveryTests.test_...` names to the existing
`python -m apps.platform_recovery.tests --pg-bin ...` command under the same helper.
Counts overlap with the 22-test run; they are not additive coverage/progress.

Ruff check/format and staged whitespace checks passed. Reopened-process tests run
Django system checks and migration-drift checks. No new model/migration exists.
Ruff initially requested a named reader function and formatting of documentation
code blocks; both were fixed. Review added copied-context and missing-nonce tests
and hardening; no unsuccessful runtime assertion was relabeled as a pass.

Temporary clusters/artifacts and synthetic key directories were cleaned by their
own test lifecycles. No key, SQL archive, private original or capability was
committed or uploaded as an artifact. Unknown target databases were deliberately
left untouched by recovery and removed only with their separately owned disposable
cluster at helper teardown.

## Remaining integration and operating limits

- Integrator must attach the [maintenance guard](V11_CONTRACT.md) to **all** shared
  mutation/GC boundaries and move the connected V11 journey to `encrypted.*`.
  No claim is made that unmodified shared writers are already gated.
- V11 PostgreSQL 18 and connected-browser integration are **NOT RUN in this lane**.
  V10's published PG18/browser evidence does not substitute for a V11 run.
- FROZEN requires one authoritative control directory used by every process.
  Nonparticipating writers, unsupported remote/NFS locking and production operation
  remain outside this local cooperative contract.
- Authenticated in-memory backups are bounded to 32 MiB file bytes/64 MiB token.
  No streaming/scale/KMS/key-rotation service, secure memory erasure, scheduler,
  production retention/cutover, or formal crypto/security acceptance is claimed.
- Targets without a previously recorded matching nonce remain unknown and
  preserved; confirmation cannot grant ownership. READY targets remain protected.
- External identity/verification configuration is explicitly reattached, not
  copied as secrets or invented grants. Legacy V10 plaintext API is preserved
  for compatibility and clearly labeled; it is not V11's encrypted operation.

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
Owner reference **74% ±8** unchanged; updated estimates belong to leadership.
