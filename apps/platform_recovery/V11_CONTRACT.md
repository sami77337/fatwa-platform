# V11 E — maintenance, encryption and verified quarantine

Base: PR #229 / `0f90bb4f6c4ba426055fc77a3a783c2061d6ee19`, verified against
GitHub metadata and `git ls-remote`. Branch: `codex/20261117-v11-recovery`.
Only `apps/platform_recovery/**` is owned/changed. The V10 branch/API is preserved.
Owner reference **74% ±8** is not recalculated.

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
Synthetic, disposable Linux PostgreSQL and private filesystem only. No production,
external sending, real data, U03 grants, scanner, automated fatwa approval, recurring
backup job, cloud key, host security setting or service deployment is introduced.

## Integrator: authoritative maintenance gate

Create **one** owned 0700 control directory under `/tmp` per synthetic database/
private store. All HTTP processes, worker processes, CLI writers, conversions and
GC must use that same directory. Set the integration-owned Django setting:

```python
FATWA_RECOVERY_MAINTENANCE_ROOT = str(control_root)
```

This lane does not edit shared settings, middleware, domain services or media
adapters. **The integrator must connect the guard at all mutation boundaries.**
An unwrapped writer/GC does not obey this cooperative gate. Until those bindings
are complete, keep V10's stopped-writers/GC prerequisite. The existing PostgreSQL
SHARE locks remain defense in depth; they do not replace filesystem GC admission.
No global database privilege or OS security setting is changed.

Initialize once while startup writers are stopped; initialization binds the
control to the existing synthetic ownership marker's database name/OID, PostgreSQL
cluster system identifier and private root. Reinitialization validates and returns
the existing state; it never clears maintenance after a crash.

```python
from apps.platform_recovery import maintenance

maintenance.initialize(root=control_root, storage=storage, synthetic_fixtures_only=True)

# Wrap OUTSIDE all filesystem digest locks and the outermost DB transaction.
with maintenance.mutation_guard(operation="WRITE", synthetic_fixtures_only=True):
    existing_source_or_case_or_answer_service(...)
# Keep admission through commit, binding completion and on_commit side effects.

with maintenance.mutation_guard(operation="GC", synthetic_fixtures_only=True):
    storage.collect_orphans(existing_reference_callback, dry_run=True)
```

Both WRITE and GC use the same lease; operation names grant no application
permission. Existing identity/role/case-scope checks remain required. Nesting in the
same synchronous execution is supported. Copied contexts cannot reuse a released
lease or a lease from a different thread/task. This is a synchronous context API;
do not carry a live lease into streaming/background work. Such work must acquire
its own admission before it starts and hold it until it finishes.

Suggested integration coverage: source intake/review/linking; requester question,
followup/upload/token operations; case/answer/citation/review/private-release
writes; publication/knowledge decisions; delivery plan/outcome/queue writes;
storage conversion, orphan cleanup and migrations. Include session/audit writes
and any GET handler that writes. A one-time status check or guarding POST alone
is insufficient. A middleware wrapper must surround the entire downstream
response/middleware unit if that unit can write. Map blocked/busy states to a
maintenance response, never fall through and execute the mutation anyway.

The transition protocol is:

1. `maintenance.enter(root=..., synthetic_fixtures_only=True)` durably records
   `DRAINING`, so new WRITE/GC attempts fail closed.
2. Existing mutation leases finish normally. Enter returns `DRAINING` if any are
   active; retry after they finish. It does not kill clients or wait indefinitely.
3. Enter returns `FROZEN` and its `generation` when drained. Encrypted snapshot
   requires FROZEN and holds the admin/activity locks through capture/encryption/
   publication. Resume cannot race a snapshot. Unknown/missing binding fails closed.
4. Success, failure or process death **does not auto-resume**. Inspect results first.
   Explicitly call `resume(root=..., expected_generation=returned_generation,
   confirmed=True, synthetic_fixtures_only=True)`. A stale generation is rejected.

Read-only requests may remain available only if their entire path truly performs
no writes; no new authority or exemption is provided here. Control files are
local private operational metadata, not a public status endpoint.

## Integrator: encrypted capture and full restore

Use the already pinned `cryptography` dependency's high-level
[Fernet authenticated-encryption recipe](https://cryptography.io/en/latest/fernet/).
There is no home-built cipher, KDF, nonce construction or encryption mode. Fernet
uses its standard authenticated token format; it exposes generation time and
ciphertext size. This choice is an engineering implementation for a bounded
synthetic drill, not a formal cryptographic/production acceptance claim.

Generate a random synthetic key with `encrypted.generate_key(path=key_file,
synthetic_fixtures_only=True)`. The key file is private, exclusively created, and
must live in a **separate temporary key directory outside the repository and
backup/restore artifact roots**, outside source storage and outside the maintenance
control. No key bytes go in arguments, environment variables, logs or receipts.
Supply only its path. Existing keys are never overwritten. Lost keys cannot be
recovered by this service. Do not upload the key directory as test evidence.

```python
from apps.platform_recovery import encrypted

sealed = encrypted.snapshot(
    scratch=artifact_root,
    storage=storage,
    pg_bin=pg_bin,
    key_file=key_file,
    maintenance_root=control_root,
    synthetic_fixtures_only=True,
)
# Retain ciphertext_sha256 independently as the expected artifact pin.
verified = encrypted.verify(
    bundle=sealed["bundle"],
    expected_ciphertext_sha256=sealed["ciphertext_sha256"],
    key_file=key_file,
)
restored = encrypted.restore(
    bundle=sealed["bundle"],
    expected_ciphertext_sha256=sealed["ciphertext_sha256"],
    key_file=key_file,
    scratch=fresh_target_parent,
    pg_bin=pg_bin,
    synthetic_fixtures_only=True,
)
assert restored["state"] == "READY"
```

The V10 PostgreSQL snapshot, manifest/baseline hashing, private storage and restore
engine are reused. Capture assembles the same verified file inventory in memory,
then authenticates/encrypts the entire envelope (SQL dump, schema, manifest and
external originals). Only `backup.fernet` and its final `COMPLETE` ciphertext hash
are published to the sealed directory. Interrupted publication never creates a
usable backup. There is **no plaintext dump/manifest staging file** on this path.

Decryption/authentication, the independent ciphertext pin, the inner manifest,
all object hashes and the exact inventory are checked **before database creation**.
The archive is passed directly to `pg_restore` on stdin for its existing phases;
no tar extraction or plaintext archive staging is used. Restored private files are
written through the existing V9 adapter to the newly created private root. Existing
case/evidence/answer/approval/permission checks and schema verification remain.

Bound: at most **32 MiB** of captured file bytes and **64 MiB** of Fernet token.
This is an in-memory synthetic drill, not streaming production backup. Oversize
input fails; OS process memory/swap is not a protected secret store and no secure
memory-erasure claim is made. Source DB/files and successfully restored DB/files
are necessarily readable by their existing private adapters; encryption covers
the backup representation. The test-only legacy V10 fixture still exercises its
plaintext compatibility path, but that is not V11's backup output.

The key authenticates the bundle; the separately retained ciphertext pin selects
the intended snapshot. Keep both. Only trusted local synthetic archives are
supported: possession of an encryption key does not make arbitrary SQL safe.
External identity/verifier configuration still requires explicit reattachment;
restoration does not copy production secrets or create authorization grants.

## Restore inspection and quarantine reconciliation

Every restore/rollback owns an exclusive `operation.lock` until it completes.
Another process cannot roll it back or reconcile it mid-operation. A crash releases
the OS lock; copied/stale execution contexts cannot bypass the real lock.

`admin.inspect_restore(target=..., synthetic_fixtures_only=True)` returns only a
state, recommended action and opaque `inspection_sha256`; no database contents,
nonce, token, filename inventory or key is exposed. `BUSY` means wait. A recorded
READY target is preserved; identity drift is reported as unknown.

A process killed after CREATE DATABASE and the unique nonce comment but before
its journal records the OID can now be recovered explicitly:

1. Inspect: `IDENTITY_RECONCILABLE` requires the exact generated database name,
   a valid full recovery nonce already matching its comment and the expected owner.
2. Call `admin.reconcile(target=..., expected_inspection_sha256=report_pin,
   confirmed=True, synthetic_fixtures_only=True)` after reviewing that inspection.
   It rechecks the same current evidence while holding the target lock. Stale
   evidence is rejected. It records the observed OID as `FAILED_IDENTITY_RECONCILED`.
   **It does not create a nonce, claim a database or delete anything.**
3. Inspect now reports `OWNED_QUARANTINE`; call the existing identity-checked
   `service.rollback(..., offline=True, synthetic_fixtures_only=True)` and retry
   the authenticated backup into a completely new target. Files remain preserved.

A crash **before the database nonce exists**, an invalid/missing nonce, ownership
or OID mismatch remains `UNKNOWN_PRESERVED`/invalid. Confirmation does not override
that refusal. Keep the unknown target for manual inspection; only the separately
owned disposable test cluster's lifecycle may remove it. No guessed DB DROP,
forced client termination, existing-database restore, automatic cutover or target
file deletion is introduced. Existing V10 READY-publication recovery is retained.

## Local CLI

All commands require `--offline-synthetic`. Root paths must be existing owned 0700
`/tmp` directories. Use the existing guarded campaign profile/environment; no DB
URL/password/service override is accepted. Paths below are placeholders.

```sh
python -m apps.platform_recovery key-create --offline-synthetic --key-file /tmp/KEYS/backup.key
python -m apps.platform_recovery maintenance-init --offline-synthetic \
  --maintenance-root /tmp/CONTROL --private-root /tmp/SOURCE
python -m apps.platform_recovery maintenance-enter --offline-synthetic --maintenance-root /tmp/CONTROL
python -m apps.platform_recovery maintenance-status --offline-synthetic --maintenance-root /tmp/CONTROL
python -m apps.platform_recovery snapshot --offline-synthetic \
  --maintenance-root /tmp/CONTROL --private-root /tmp/SOURCE --scratch /tmp/ARTIFACTS \
  --pg-bin /path/to/postgresql/bin --key-file /tmp/KEYS/backup.key
python -m apps.platform_recovery backup-status --offline-synthetic --bundle /tmp/ARTIFACTS/sealed-ID
python -m apps.platform_recovery verify --offline-synthetic --bundle /tmp/ARTIFACTS/sealed-ID \
  --ciphertext-sha256 PIN --key-file /tmp/KEYS/backup.key
python -m apps.platform_recovery restore --offline-synthetic --bundle /tmp/ARTIFACTS/sealed-ID \
  --ciphertext-sha256 PIN --key-file /tmp/KEYS/backup.key --scratch /tmp/TARGETS --pg-bin /path/to/postgresql/bin
python -m apps.platform_recovery restore-status --offline-synthetic --target /tmp/TARGETS/restore-ID
python -m apps.platform_recovery reconcile --offline-synthetic --target /tmp/TARGETS/restore-ID \
  --inspection-sha256 INSPECTION_PIN --confirm
python -m apps.platform_recovery rollback --offline-synthetic --target /tmp/TARGETS/restore-ID
python -m apps.platform_recovery maintenance-resume --offline-synthetic \
  --maintenance-root /tmp/CONTROL --generation GENERATION --confirm
```

`backup-status` is intentionally `SEALED_UNAUTHENTICATED` until a key+expected pin
are supplied to `verify`. Status commands never report plaintext content or keys.
The CLI removes nonce/failure details from operation receipts. Restore receipts
include only the operational handles needed for explicitly reopening the new
synthetic application process; none of these commands is a web admin permission.

Legacy V10 Python callers remain compatible; CLI plaintext operations are now
explicitly `legacy-snapshot`, `legacy-verify`, `legacy-restore`. The coordinator
must move the V11 connected journey to `encrypted.*` and attach mutation guards.
See [V11_EVIDENCE.md](V11_EVIDENCE.md) for actual tests and remaining integration work.
