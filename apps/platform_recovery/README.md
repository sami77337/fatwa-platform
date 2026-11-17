# V11 recovery entry point

V11 adds durable maintenance admission, authenticated encrypted backups, and
nonce-verified quarantine inspection/reconciliation. Read [V11_CONTRACT.md](V11_CONTRACT.md)
for the integration/API/CLI contract and [V11_EVIDENCE.md](V11_EVIDENCE.md) for validation.
The `snapshot`, `verify`, and `restore` CLI commands now use encrypted V11 bundles.
The original V10 Python API remains compatible; its plaintext CLI is explicitly
named `legacy-snapshot`, `legacy-verify`, and `legacy-restore`.

The following section is the preserved V10 operating contract, not a claim that
legacy plaintext backups provide V11 encryption or maintenance enforcement.

# V10 platform recovery — synthetic offline drill

Base: PR #228, `12840d54c263e63b214ce72eff1d8b4f93f9900e` (GitHub head verified
before branching). Ownership is exclusively `apps/platform_recovery/**`.
No shared settings, models, migrations, media adapters or routes are modified.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.** No production
operation, real requester data, cloud/production credentials, external sending,
scanner, automatic scholarly approval or new organizer permission is introduced.

## Integration contract

Import `apps.platform_recovery.service` **after `django.setup()`** with the existing
`config.settings.campaign_review` profile. No app registration or migration is
needed. Use PostgreSQL 17/18 and its `pg_dump`/`pg_restore` client binaries. The
existing V9 `FileSystemStorage`, `StoredOriginal`, byte verification, digest locks,
restore API and durable owner registry are reused.

```python
from apps.platform_recovery.service import snapshot, verify_bundle, restore

# scratch is an existing owned 0700 TemporaryDirectory under /tmp.
# storage is the currently configured V9 FileSystemStorage, also under /tmp.
backup = snapshot(
    scratch=scratch, storage=storage, pg_bin=pg_bin, synthetic_fixtures_only=True, offline=True
)
# Retain this digest separately from the bundle: it is the trusted baseline pin.
pin = backup["manifest_sha256"]
verify_bundle(backup["bundle"], pin)
recovered = restore(
    bundle=backup["bundle"],
    expected_manifest_sha256=pin,
    scratch=scratch,
    pg_bin=pg_bin,
    synthetic_fixtures_only=True,
    offline=True,
)
assert recovered["state"] == "READY"
# Only now reopen an isolated application process with:
# PGDATABASE=recovered["database"]
# PGTESTDATABASE="test_" + recovered["database"]
# FATWA_PRIVATE_MEDIA_STORAGE=FileSystemStorage(recovered["private_root"],
#                                             synthetic_fixtures_only=True)
```

The integrator must stop the application server, workers, migrations, storage
conversion/GC and other writers before setting `offline=True`. This argument is
an explicit operational acknowledgement, **not a global lock honored by other
apps**. Keep them stopped until snapshot returns (or fails). Existing code is not
changed to implement an online maintenance mode. Database SHARE locks block
ordinary concurrent DML, an exported repeatable-read snapshot binds the SQL dump
to its row baseline, and V9 digest locks protect referenced filesystem copies.
The five-second DB lock timeout fails closed if a writer conflicts; no writer is
terminated. Sequence values are compared before/after copying because sequence
state is not MVCC. Never run a source migration concurrently.

The snapshot includes **every public ordinary table**, all row/column hashes,
sequence state, schema (including constraints, triggers, functions, owners and
ACLs), and all immutable originals referenced by both V9 owner tables, including
historical answer revisions and inline bytes in the DB. The supported owner
registry must match V9 exactly; missing schemas or new owners require explicit
support. Other user schemas, partitioned and foreign tables fail closed. Database encoding/
collation must match the cluster's template0; nondefault database ACLs, connection
limits or persistent database/role settings are rejected instead of silently lost.
Object ACLs/owners remain part of schema verification. Fingerprint sessions use
fixed UTC/date/interval/bytea/float formats, including across independent servers.
Unreferenced or quarantined store objects and lock files are preserved in the
source, but are not live platform references and are not included in the bundle.

The manifest contains a per-table row-count/hash baseline and per-owner
backend/key/size/SHA-256 inventory; it contains no inline payload or credentials.
`database.dump`, `schema.sql` and every external object are pinned. `COMPLETE` is
written and fsynced last. Partial snapshots remain private and cannot be restored.
The digest pin detects corruption; it is **not a signature or authentication of
an untrusted SQL archive**. Restore only locally generated trusted drill bundles.

Restoration creates a random, exclusively owned **new database and private root**;
there is no target-database argument, `--clean`, existing-root reuse, forced drop,
or source-file deletion. It can run in a newly initialized isolated cluster using
the same guarded campaign profile. Current profile must already own its synthetic
administrative database (the existing helper supplies this).

Pre-data and data are restored before the existing synthetic ownership marker is
rebound to the new name/OID. Its scope/source/contract are checked unchanged.
Post-data reinstalls all integrity guards and validates FKs against restored rows.
All row/sequence, reference, asset and schema fingerprints must then match.
Only physical name/OID columns in the ownership marker are excluded from row
comparison. This preserves case/evidence/answer/release/access-token associations;
it does not create new grants or approval decisions.

PostgreSQL re-deparses varchar literal-array casts after a restore. Schema hashing
normalizes only that exact literal-array cast form in CHECK lines and the random
psql `restrict` nonce; it retains every literal, constraint, trigger and SQL body.
A disabled ownership trigger and a cross-case row mutation are tested failures.

`READY` is the completion boundary. The service does **not** switch an existing
application or expose a restored DB via HTTP. Reopen a fresh process explicitly.
External/in-memory identity directories, verifier objects and secrets are not
backed up. Missing authority stays denied. The test reattaches the original
explicit synthetic authority to verify allowed access and unchanged denials; the
integrator must do the same for its synthetic identity/provider fixtures.

## Standalone commands

Set up the same guarded, credential-free temporary PostgreSQL environment as V9.
All output and source private roots must be owned 0700 paths under `/tmp`.
The CLI never receives a DB URL, password, archive SQL, target DB name or token.

```sh
python -m apps.platform_recovery legacy-snapshot --offline-synthetic \
  --scratch /tmp/OWNED_DRILL --private-root /tmp/OWNED_SOURCE \
  --pg-bin /path/to/postgresql/bin

python -m apps.platform_recovery legacy-verify --offline-synthetic \
  --bundle /tmp/OWNED_DRILL/snapshot-ID --manifest-sha256 RETAINED_DIGEST

python -m apps.platform_recovery legacy-restore --offline-synthetic \
  --scratch /tmp/OWNED_DRILL --pg-bin /path/to/postgresql/bin \
  --bundle /tmp/OWNED_DRILL/snapshot-ID --manifest-sha256 RETAINED_DIGEST

python -m apps.platform_recovery rollback --offline-synthetic \
  --target /tmp/OWNED_DRILL/restore-ID
```

Placeholders must be replaced with actual paths/output. Source is restricted by
the existing Wave7 ownership guard, `FATWA_PRODUCTION=0`, synthetic-write opt-in,
loopback host and synthetic database role/name. Password-bearing profiles are
rejected; libpq service/password-file overrides are not accepted. These are local
trust-authenticated disposable clusters, not deployment configuration.

## Storage incident procedure

1. Stop writers/GC and retain the bundle plus the separately pinned digest.
   Missing or corrupt source bytes abort backup; do not relabel a partial copy as
   complete. This service never repairs or deletes a source original.
2. Verify the existing complete backup before creating a recovery target.
   Missing/corrupt objects, dump/schema damage, changed manifest, links or extra
   objects fail before target creation. Preserve damaged evidence for diagnosis.
3. Restore to a fresh target. On normal failure, only the generated DB with the
   recorded OID **and nonce comment** is dropped. Target files and journal remain
   private for inspection. Retry the verified backup into another fresh target.
4. After a process crash, read the target's `journal.json`. `RESTORING` is never
   usable. Run `rollback` to check the exact DB identity and remove that staged DB;
   files remain. Repeated rollback is safe. A connected consumer prevents DROP:
   stop that consumer and retry; the tool never force-disconnects it.
5. A crash in the small CREATE-DATABASE-to-durable-journal window can leave a
   `PREPARING` journal without a usable OID/nonce. It is deliberately **manual
   quarantine**, not permission to guess and delete a DB. Retain the entire
   disposable cluster for inspection or discard that separately owned cluster.
   An identity mismatch, unavailable DB or cleanup error likewise remains pending.
6. `READY` targets cannot be removed by rollback. Verify service behavior in a new
   process, then perform an explicit synthetic application cutover. Keep the
   source and backup intact. There is no production cutover or retention policy.

The recovery artifacts, including incomplete files, are private but unencrypted.
They may contain synthetic capability tokens in the SQL dump. Do not commit them,
serve them, send them externally, or use this bounded drill with real data.
Artifacts remain under the caller's temporary directory for its normal lifecycle.

## Tests and evidence

Run on a **fresh** cluster using existing infrastructure (all new tests are here):

```sh
python -m infra.dev.with_casework_postgres \
  --pg-bin /path/to/postgresql/bin --major 17 \
  --settings config.settings.campaign_review -- \
  python -m apps.platform_recovery.tests --pg-bin /path/to/postgresql/bin
```

This is a standalone `unittest` drill, not a new Django app/test-runner profile.
`verify_fixture.py` reopens the restored environment in a separate process and
checks exact attachment/audio bytes (including retained revisions), evidence and
answer versions, current independent approval/private release, other-case and
organizer denials, missing-authority denial, immutable SQL protections and stale
answer closure after new facts. It also runs system/migration-drift checks.

The independent-cluster test also starts a second fresh PostgreSQL server, restores
there, reopens the application and runs the same service checks while that server
is alive; no existing destination application database is reused.

Additional tests cover missing/corrupt source and backup bytes, broken dump and
manifest, unfinished snapshots, symlinks/extra inventory, DML freeze, every restore
phase fault, real process death, disk-write failure after a partial copy, failed
failure-journal write, nondefault DB policy rejection, rollback
retry with an open consumer, wrong OID/nonce, existing-name collision, absent
schema, new media owner, and schema/cross-case tampering.

See [EVIDENCE.md](EVIDENCE.md) for actual local results and remaining limits.
