# V12 P0 — encrypted-only recovery policy

Verified base: PR #230 and remote `codex/20261117-v11-integration` at
`5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`. Work branch:
`codex/20261117-v12-recovery`; V11 and its history are preserved.

Scope is **P0 only**. Existing source/case/answer/private-media services, Fernet,
maintenance and restore engine are reused. No P1 work or readiness estimate.
Owner reference **79% ±8** is unchanged and is not acceptance.

## Strict setting for the integrator

Set these values explicitly in the integration-owned V11/V12 settings:

```python
FATWA_RECOVERY_ENCRYPTION_REQUIRED = True
FATWA_RECOVERY_V10_TEST_COMPAT = False
```

The implementation already defaults to encryption required when the setting is
absent. Values must be actual booleans: `0`, `"false"` and other truthy/falsy
substitutes cannot downgrade the policy. Even setting both compatibility flags in
an ordinary application profile does not enable plaintext operations.

`service.snapshot()` without the internal in-memory capture argument and
`service.restore()` without the internal authenticated file map now reject with
`plaintext_recovery_disabled`. Rejection occurs before a dump, output/target
creation or database restore. The CLI checks `legacy-snapshot` and `legacy-restore`
before even opening/initializing the source storage adapter. There is no CLI
`--allow-plaintext` override and no automatic fallback after encryption failure.

Use the existing public `encrypted.snapshot`, `encrypted.verify` and
`encrypted.restore` APIs and normal CLI `snapshot`, `verify`, `restore`. Their
call/receipt contracts remain unchanged. The underscored `_capture` and `_files`
arguments in the low-level engine are internal in-memory seams for the encrypted
orchestrator, not a supported legacy bypass. Capture accepts only a fresh plain
dictionary and creates no unencrypted disk bundle. This policy does not claim to
contain an administrator executing arbitrary Python/SQL outside these APIs.

Read-only `legacy-verify` may inspect an existing trusted synthetic V10 artifact;
it neither creates a bundle nor authorizes plaintext restore.

## V10 compatibility — separate test profile only

The sole plaintext exception is the explicit profile
`apps.platform_recovery.v12_recovery_v10_test_settings` with:

```python
FATWA_RECOVERY_ENCRYPTION_REQUIRED = False
FATWA_RECOVERY_V10_TEST_COMPAT = True
```

Both values **and the exact settings module identity** are required. Strict=True
wins even inside that profile. The profile inherits the existing synthetic
campaign settings and must be selected only inside a separately owned disposable
PostgreSQL test cluster. Never start a V11/V12 application or pilot with it.
Production/ownership/synthetic guards are still required; no target can be reused.

**Integrator-owned follow-up:** legacy `apps.platform_recovery.tests` and the
existing `tests_v11.py` bootstrap call a plaintext V10 fixture. Existing V10 browser/
demo fixtures also call the low-level plaintext API. Run genuinely legacy
compatibility checks using this separate test profile, or adapt their fixture
construction under integration ownership. Do not disable strict mode in the
V11/V12 runtime to make those fixtures pass. The new P0 suite constructs its own
fixture directly through existing services under the ordinary strict profile.

Example compatibility invocation (a separate cluster from the strict suite):

```sh
python -m infra.dev.with_casework_postgres \
  --pg-bin /path/to/postgresql/bin --major 17 \
  --settings apps.platform_recovery.v12_recovery_v10_test_settings -- \
  python -m apps.platform_recovery.tests --pg-bin /path/to/postgresql/bin
```

The P0 tests exercise the exception in a distinct settings process and verify its
restored original bytes, permissions and schema. They also prove that the same
artifact cannot be restored through an ordinary strict profile.

## Key, envelope and target invariants

- V11/V12 packages remain exactly `backup.fernet` plus final `COMPLETE`. SQL dump,
  manifest, schema and private originals remain inside the authenticated Fernet
  envelope. The encrypted path still sends the verified archive to pg_restore
  through stdin and does not materialize a plaintext backup/staging archive.
- A Fernet key must remain in its separate owned temporary key directory, outside
  repository, package/artifact roots, source storage and control root. Repository
  exclusion is explicit now, including a checkout located under `/tmp`. Existing
  no-symlink, ownership, private-mode and artifact separation checks remain.
  Key bytes are never placed in command arguments, environment or log receipts.
- Wrong/malformed/missing key, wrong/malformed pin, incomplete/modified ciphertext,
  invalid authenticated envelope structure, missing/corrupt original or changed
  inner manifest all fail **before a target directory or database is created**.
  Outer ciphertext hash alone is not authentication; Fernet verification remains
  required even when a test recomputes that hash after corrupting a token.
- No asset size/hash/schema/relation check is relaxed. Malformed authenticated
  `files` collections now fail with a fixed error instead of an attribute traceback.
  The existing exact inventory also rejects any extra plaintext file in a sealed
  bundle.
- New owned targets only. Existing nonce/OID checks, rollback, READY publication
  and unknown-pre-nonce preservation are unchanged. No unknown DB/file deletion,
  forced client termination, existing-target restore or automatic cutover.

## Ownership and integration boundary

Only `service.py`, `encrypted.py`, `__main__.py` and new `v12_recovery*` test/docs
are changed. The current tree has `integration.py` and `middleware.py`, not a
standalone `admission.py`. Neither those files nor `maintenance.py`, shared
settings, routes, CI or GitHub settings are edited here. Existing cooperative
admission remains required; its P0 strengthening belongs to its assigned owner.

Integrate and run affected PG17/18 checks before advancing to P1. The strict suite
command and actual evidence are in [v12_recovery_evidence.md](v12_recovery_evidence.md).

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
No main merge, real data/keys, production, external sending, U03 grants,
automatic scholarly approval, Meta contract assumptions or recurring backup job.
