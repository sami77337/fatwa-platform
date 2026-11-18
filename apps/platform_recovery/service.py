"""Offline recovery into exclusively created synthetic targets; no shared settings edits.

The caller stops application writers, workers, migrations and storage GC first.
Database SHARE locks/exported snapshot enforce one relational point in time;
V9 digest locks and byte checks protect its external originals during copying.
Only a verified complete bundle can create a fresh restore target. Nothing here
switches traffic, resets an existing database or deletes a source original.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path

import psycopg
from django.apps import apps
from django.conf import settings
from django.db import connection
from psycopg import sql

from apps.case_attachments.storage_bindings import OWNERS
from apps.intake_workflow.contracts import CONTRACT_VERSION, SOURCE_CONFIG_ID, SYNTHETIC_SCOPE
from apps.intake_workflow.guards import require_owned_database
from apps.private_media.filesystem import BACKEND, FileSystemStorage
from apps.private_media.storage import StoredOriginal, verify_original

from .leases import Lease, execution

FORMAT = "fatwa-platform-recovery-v1"
OWNER_TABLES = ("case_attachments_caseattachment", "answer_media_answerpart")
REQUIRED_TABLES = {
    *OWNER_TABLES,
    "casework_case",
    "casework_caseevidence",
    "casework_answerrevision",
    "casework_casedecision",
    "answer_media_privateanswerrelease",
    "django_migrations",
    "wave7_synthetic_ownership",
}
DIGEST = re.compile(r"[a-f0-9]{64}")
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
_TARGET_LEASE = ContextVar("recovery_target_lease", default=())
TARGET = re.compile(r"wave7_synthetic_restore_[a-f0-9]{24}")
NONCE = re.compile(r"synthetic-recovery:[a-f0-9]{64}")


class RecoveryError(RuntimeError):
    """Fixed code; never exposes SQL, subprocess stderr, payloads or credentials."""


def require(value, code):
    if not value:
        raise RecoveryError(code)


V10_TEST_SETTINGS = "apps.platform_recovery.v12_recovery_v10_test_settings"


def require_v10_test_profile():
    """Plaintext disk bundles are restricted to the separate V10 test composition.

    Strict mode is the fail-closed default. No CLI flag, environment override or
    ordinary profile can silently downgrade V11/V12 backup/restore to plaintext.
    This is trusted configuration policy, not a boundary against arbitrary Python.
    """
    require(
        getattr(settings, "FATWA_RECOVERY_ENCRYPTION_REQUIRED", True) is False
        and getattr(settings, "FATWA_RECOVERY_V10_TEST_COMPAT", False) is True
        and settings.SETTINGS_MODULE == V10_TEST_SETTINGS,
        "plaintext_recovery_disabled",
    )


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def safe_directory(path):
    """Only private owned real directories beneath the OS temporary directory."""
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(strict=True), "unsafe_directory")
    require(
        path.is_relative_to(Path(tempfile.gettempdir())) and path != Path(tempfile.gettempdir()),
        "temporary_targets_only",
    )
    for node in [path, *path.parents]:
        if node == Path(tempfile.gettempdir()):
            break
        info = node.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            "private_directory_required",
        )
    return path


def read_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) in (0o400, 0o600),
            "unsafe_bundle_file",
        )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def write_file(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def journal(path, value):
    pending = path / (".journal-" + secrets.token_hex(12))
    write_file(pending, canonical(value))
    os.replace(pending, path / "journal.json")
    sync_directory(path)


def guard(*, synthetic_fixtures_only, offline):
    require(synthetic_fixtures_only is True and offline is True, "offline_synthetic_ack_required")
    owned = require_owned_database(synthetic_fixtures_only=True)
    require(not settings.DATABASES["default"].get("PASSWORD"), "credential_free_cluster_required")
    require(not os.environ.get("PGPASSWORD"), "credential_free_cluster_required")
    return owned


def parameters(database=None):
    db = connection.settings_dict
    return dict(
        host="127.0.0.1",
        port=int(db["PORT"]),
        user="wave7_synthetic",
        dbname=database or db["NAME"],
        connect_timeout=5,
        password="",
        passfile="/nonexistent",
        # Row fingerprints must survive a fresh server with a different timezone.
        options="-c timezone=UTC -c datestyle=ISO,YMD -c intervalstyle=postgres "
        "-c bytea_output=hex -c extra_float_digits=3",
    )


def connect(database=None):
    return psycopg.connect(**parameters(database), autocommit=True)


class PostgresTools:
    def __init__(self, binaries):
        self.binaries = Path(binaries).resolve(strict=True)

    def run(self, tool, database, *args, input_data=None):
        # Deliberately do not inherit libpq passwords, service files or options.
        env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "HOME": "/nonexistent"}
        p = parameters(database)
        command = [
            str(self.binaries / tool),
            "--host",
            p["host"],
            "--port",
            str(p["port"]),
            "--username",
            p["user"],
            "--no-password",
            "--dbname",
            p["dbname"],
            *args,
        ]
        result = subprocess.run(
            command, env=env, input=input_data, capture_output=True, timeout=120
        )
        require(result.returncode == 0, tool + "_failed")
        return result.stdout

    def schema(self, database, snapshot=None):
        args = ["--schema-only"]
        if snapshot:
            args += ["--snapshot", snapshot]
        raw = self.run("pg_dump", database, *args).decode()
        # pg_dump adds a random psql restriction nonce; it is not schema metadata.
        # PostgreSQL reparses varchar literal arrays on restore, distributing the
        # cast to text over each element. Canonicalize ONLY this exact literal
        # form on CHECK constraint lines; retain all values, names and SQL bodies.
        literal = r"'(?:[^']|'')*'::character varying"
        array = re.compile(r"\(ARRAY\[((?:" + literal + r")(?:, " + literal + r")*)\]\)::text\[\]")
        lines = []
        for line in raw.splitlines():
            if line.startswith(("\\restrict ", "\\unrestrict ")):
                continue
            if line.lstrip().startswith("CONSTRAINT ") and " CHECK " in line:
                line = array.sub(
                    lambda match: (
                        "ARRAY["
                        + re.sub(literal, lambda item: "(" + item[0] + ")::text", match[1])
                        + "]"
                    ),
                    line,
                )
            lines.append(line)
        return "\n".join(lines).encode()


def database_profile(db):
    """No silent loss of database-level ACLs, locale or persistent role settings.

    This drill supports the existing default template0 profile only; object ACLs
    remain in the archive. Configured database/role policies need a wider contract.
    """
    row = db.execute(
        "SELECT to_jsonb(d) FROM pg_database d WHERE datname=current_database()"
    ).fetchone()[0]
    template = db.execute(
        "SELECT to_jsonb(d) FROM pg_database d WHERE datname='template0'"
    ).fetchone()[0]
    fields = (
        "encoding",
        "datlocprovider",
        "datcollate",
        "datctype",
        "datlocale",
        "daticulocale",
        "daticurules",
        "datcollversion",
    )
    profile = {key: row.get(key) for key in fields}
    require(profile == {key: template.get(key) for key in fields}, "database_locale_unsupported")
    require(
        row["datacl"] is None
        and row["datconnlimit"] == -1
        and row["datallowconn"]
        and not row["datistemplate"],
        "database_policy_unsupported",
    )
    require(
        not db.execute(
            "SELECT 1 FROM pg_db_role_setting WHERE setdatabase IN (0,%s)", [row["oid"]]
        ).fetchall(),
        "persistent_role_settings_unsupported",
    )
    return profile


def table_names(db):
    namespaces = db.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname NOT IN "
        "('pg_catalog','pg_toast','information_schema','public') "
        "AND nspname !~ '^pg_(toast_)?temp_[0-9]+$'"
    ).fetchall()
    require(not namespaces, "unexpected_schema")
    tables = [
        r[0]
        for r in db.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' "
            "ORDER BY c.relname"
        ).fetchall()
    ]
    require(REQUIRED_TABLES <= set(tables), "required_schema_missing")
    # This bounded implementation must not silently omit a new partitioned/foreign owner.
    require(
        not db.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('p','f')"
        ).fetchall(),
        "unsupported_table_kind",
    )
    return tables


def baseline(db):
    """Every row/column (including durable grants, versions and audit) + sequence state."""
    result = {}
    for name in table_names(db):
        expression = sql.SQL("to_jsonb(t)")
        if name == "wave7_synthetic_ownership":
            # Only physical target identity changes; all scope/contract fields stay pinned.
            expression = sql.SQL("to_jsonb(t) - 'database_name' - 'database_oid'")
        rows = db.execute(
            sql.SQL("SELECT ({})::text FROM public.{} t").format(expression, sql.Identifier(name))
        ).fetchall()
        hashes = sorted(digest(row[0].encode()) for row in rows)
        result[name] = {"rows": len(rows), "sha256": digest(canonical(hashes))}
    sequences = {}
    for (name,) in db.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='S' "
        "ORDER BY c.relname"
    ).fetchall():
        sequences[name] = list(
            db.execute(
                sql.SQL("SELECT last_value,is_called FROM public.{}").format(sql.Identifier(name))
            ).fetchone()
        )
    return {"tables": result, "sequences": sequences}


def references(db):
    # Reuse the V9 durable-owner registry and fail closed if its contract grows.
    try:
        registered = {
            apps.get_model(label, model)._meta.db_table for label, model in OWNERS.values()
        }
    except LookupError:
        raise RecoveryError("media_owner_registry_unavailable") from None
    require(registered == set(OWNER_TABLES), "media_owner_registry_changed")
    result = []
    for table in OWNER_TABLES:
        rows = db.execute(
            sql.SQL(
                "SELECT id,storage_backend,storage_key,sha256,size,original "
                "FROM public.{} ORDER BY id"
            ).format(sql.Identifier(table))
        )
        for owner_id, backend, key, sha, size, inline in rows:
            original = StoredOriginal(
                backend, key or sha, sha, size, bytes(inline) if inline is not None else None
            )
            if backend == "inline-database-v1":
                verify_original(original.inline, sha, size)
            else:
                require(
                    backend == BACKEND
                    and inline is None
                    and key == sha + ".blob"
                    and DIGEST.fullmatch(sha),
                    "unknown_storage_reference",
                )
            result.append(
                {
                    "table": table,
                    "id": str(owner_id),
                    "backend": backend,
                    "key": original.key,
                    "sha256": sha,
                    "size": size,
                }
            )
    return result


def original(item):
    return StoredOriginal(item["backend"], item["key"], item["sha256"], item["size"])


def checkpoint(stage):
    """Fault-injection seam used by the isolated integration tests; no runtime flag."""


def snapshot(
    *, scratch, storage, pg_bin, synthetic_fixtures_only=False, offline=False, _capture=None
):
    """V10 test disk bundle, or bounded in-memory capture for the encrypted engine."""
    if _capture is None:
        require_v10_test_profile()
    else:
        require(type(_capture) is dict and not _capture, "invalid_memory_capture")
    owned = guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=offline)
    require(isinstance(storage, FileSystemStorage), "filesystem_adapter_required")
    safe_directory(storage.root)
    parent = safe_directory(scratch)
    bundle = Path(tempfile.mkdtemp(prefix="snapshot-", dir=parent)) if _capture is None else None
    captured_size = 0

    def emit(name, raw):
        nonlocal captured_size
        if _capture is None:
            write_file(bundle / name, raw)
        else:
            captured_size += len(raw)
            require(captured_size <= MAX_CAPTURE_BYTES, "encrypted_drill_size_limit")
            _capture[name] = raw

    tools = PostgresTools(pg_bin)
    try:
        with connect() as db, db.transaction(), ExitStack() as locks:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            db.execute("SET LOCAL lock_timeout='5s'")
            db.execute("SELECT pg_advisory_xact_lock(73907, 1710)")
            profile = database_profile(db)
            tables = table_names(db)
            db.execute(
                sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
                    sql.SQL(",").join(sql.Identifier("public", name) for name in tables)
                )
            )
            snap = db.execute("SELECT pg_export_snapshot()").fetchone()[0]
            before = baseline(db)
            refs = references(db)
            assets = {}
            for item in refs:
                if item["backend"] == BACKEND:
                    assets[item["key"]] = item
            for key in sorted(assets):
                locks.enter_context(storage.binding_lock(assets[key]["sha256"]))
            checkpoint("frozen")
            if bundle is not None:
                (bundle / "objects").mkdir(mode=0o700)
            for key, item in sorted(assets.items()):
                emit("objects/" + key, storage.get(original(item)))
            schema = tools.schema(owned.database_name, snap)
            archive = tools.run(
                "pg_dump", owned.database_name, "--format=custom", "--no-owner", "--snapshot", snap
            )
            emit("database.dump", archive)
            emit("schema.sql", schema)
            require(baseline(db) == before, "source_changed_during_freeze")
            # Fail closed if external bytes changed during the database dump.
            for item in assets.values():
                storage.get(original(item))
            manifest = {
                "format": FORMAT,
                "scope": "SYNTHETIC_ONLY",
                "database_profile": profile,
                "baseline": before,
                "references": refs,
                "dump_sha256": digest(archive),
                "schema_sha256": digest(schema),
                "postgres_major": db.info.server_version // 10000,
            }
            payload = canonical(manifest)
            emit("manifest.json", payload)
            if bundle is not None:
                sync_directory(bundle / "objects")
                sync_directory(bundle)
            # Last file is the publication boundary: interrupted copies are not backups.
            emit("COMPLETE", digest(payload).encode())
            if bundle is not None:
                sync_directory(bundle)
                sync_directory(parent)
            return {
                "bundle": str(bundle) if bundle is not None else None,
                "manifest_sha256": digest(payload),
                "assets": len(assets),
                "tables": len(before["tables"]),
            }
    except BaseException:
        # Preserve incomplete evidence, never touch the live store or destroy the bundle.
        raise


def verify_bundle(bundle, expected_manifest_sha256, *, _files=None):
    if _files is None:
        bundle = safe_directory(bundle)

        def fetch(name):
            return read_file(bundle / name)
    else:
        require(
            type(_files) is dict
            and all(type(k) is str and type(v) is bytes for k, v in _files.items()),
            "invalid_memory_bundle",
        )
        require(sum(map(len, _files.values())) <= MAX_CAPTURE_BYTES, "encrypted_drill_size_limit")
        fetch = _files.__getitem__
    require(
        isinstance(expected_manifest_sha256, str) and DIGEST.fullmatch(expected_manifest_sha256),
        "manifest_pin_required",
    )
    payload = fetch("manifest.json")
    require(
        digest(payload) == expected_manifest_sha256
        and fetch("COMPLETE") == expected_manifest_sha256.encode(),
        "manifest_integrity_failed",
    )
    manifest = json.loads(payload)
    require(
        manifest["format"] == FORMAT and manifest["scope"] == "SYNTHETIC_ONLY",
        "unknown_bundle_format",
    )
    require(
        digest(fetch("database.dump")) == manifest["dump_sha256"],
        "dump_integrity_failed",
    )
    require(
        digest(fetch("schema.sql")) == manifest["schema_sha256"],
        "schema_integrity_failed",
    )
    if _files is None:
        safe_directory(bundle / "objects")
    keys = set()
    for item in manifest["references"]:
        require(
            item["table"] in OWNER_TABLES and DIGEST.fullmatch(item["sha256"]),
            "manifest_reference_invalid",
        )
        if item["backend"] == BACKEND:
            require(item["key"] == item["sha256"] + ".blob", "manifest_reference_invalid")
            keys.add(item["key"])
            verify_original(fetch("objects/" + item["key"]), item["sha256"], item["size"])
        else:
            require(item["backend"] == "inline-database-v1", "unknown_storage_reference")
    if _files is None:
        require(set(os.listdir(bundle / "objects")) == keys, "asset_inventory_mismatch")
        require(
            set(os.listdir(bundle))
            == {"objects", "database.dump", "schema.sql", "manifest.json", "COMPLETE"},
            "bundle_inventory_mismatch",
        )
    else:
        require(
            set(_files)
            == {"database.dump", "schema.sql", "manifest.json", "COMPLETE"}
            | {"objects/" + key for key in keys},
            "bundle_inventory_mismatch",
        )
    return manifest


@contextmanager
def target_operation(target):
    """Cross-process exclusive ownership of one restore operation; never a stale PID test."""
    import fcntl

    target = safe_directory(target)
    held = _TARGET_LEASE.get()
    if any(lease.matches(target) for lease in held):
        yield
        return
    fd = os.open(target / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o600,
            "unsafe_operation_lock",
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryError("target_operation_busy") from None
        lease = Lease(str(target), execution())
        token = _TARGET_LEASE.set((*held, lease))
        try:
            yield
        finally:
            lease.active = False
            _TARGET_LEASE.reset(token)
    finally:
        os.close(fd)


def rollback(*, target, synthetic_fixtures_only=False, offline=False):
    with target_operation(target):
        return _rollback(
            target=target, synthetic_fixtures_only=synthetic_fixtures_only, offline=offline
        )


def _rollback(*, target, synthetic_fixtures_only=False, offline=False):
    """Drop only this journal's new DB with matching OID+nonce; retain all target files.

    Can be repeated after a process crash. Never force-disconnect a live consumer.
    A READY target is deliberately ineligible for rollback by this function.
    """
    guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=offline)
    target = safe_directory(target)
    state = json.loads(read_file(target / "journal.json"))
    require(
        state["format"] == FORMAT
        and TARGET.fullmatch(state["database"])
        and state["state"] != "READY",
        "rollback_target_ineligible",
    )
    require(
        type(state.get("nonce")) is str and NONCE.fullmatch(state["nonce"]),
        "rollback_identity_mismatch",
    )
    with connect() as admin:
        identity = admin.execute(
            "SELECT oid,shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s",
            [state["database"]],
        ).fetchone()
        if identity:
            require(identity == (state["oid"], state["nonce"]), "rollback_identity_mismatch")
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(state["database"])))
    state["state"] = "ROLLED_BACK_FILES_PRESERVED"
    journal(target, state)
    return state


def restore(
    *,
    bundle,
    expected_manifest_sha256,
    scratch,
    pg_bin,
    synthetic_fixtures_only=False,
    offline=False,
    _files=None,
):
    """Creates a random DB + private store, validates everything, then writes READY.

    Callers must explicitly reopen Django against the returned DB/root only after
    READY. No caller-chosen database names, existing roots or automatic activation.
    """
    if _files is None:
        require_v10_test_profile()
    guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=offline)
    manifest = verify_bundle(bundle, expected_manifest_sha256, _files=_files)
    parent = safe_directory(scratch)
    tools = PostgresTools(pg_bin)
    target = Path(tempfile.mkdtemp(prefix="restore-", dir=parent))
    state = {
        "format": FORMAT,
        "state": "PREPARING",
        "database": "wave7_synthetic_restore_" + secrets.token_hex(12),
        "nonce": "synthetic-recovery:" + secrets.token_hex(32),
        "oid": None,
        "manifest_sha256": expected_manifest_sha256,
    }
    with target_operation(target):
        return _restore_target(
            target=target,
            state=state,
            manifest=manifest,
            tools=tools,
            bundle=bundle,
            expected_manifest_sha256=expected_manifest_sha256,
            _files=_files,
        )


def _restore_target(*, target, state, manifest, tools, bundle, expected_manifest_sha256, _files):
    journal(target, state)
    created = False
    try:
        with connect() as admin:
            require(
                admin.info.server_version // 10000 == manifest["postgres_major"],
                "postgres_major_mismatch",
            )
            # CREATE DATABASE without IF NOT EXISTS: collision cannot adopt an existing DB.
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(state["database"])
                )
            )
            created = True
            checkpoint("database_created_before_identity")
            state["oid"] = admin.execute(
                "SELECT oid FROM pg_database WHERE datname=%s", [state["database"]]
            ).fetchone()[0]
            admin.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(state["database"]), sql.Literal(state["nonce"])
                )
            )
        checkpoint("database_identity_before_journal")
        state["state"] = "RESTORING"
        journal(target, state)
        checkpoint("database_created")
        from .integration import offline_restore_files

        with offline_restore_files(target=target, state=state):
            store = FileSystemStorage(target / "private", synthetic_fixtures_only=True)
            for item in manifest["references"]:
                if item["backend"] == BACKEND:
                    store.restore(
                        original(item),
                        (
                            _files["objects/" + item["key"]]
                            if _files is not None
                            else read_file(Path(bundle) / "objects" / item["key"])
                        ),
                    )
        checkpoint("assets_restored")
        archive_args = [] if _files is not None else [str(Path(bundle) / "database.dump")]
        archive_input = _files["database.dump"] if _files is not None else None
        for section in ("pre-data", "data"):
            tools.run(
                "pg_restore",
                state["database"],
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--section=" + section,
                *archive_args,
                input_data=archive_input,
            )
            checkpoint(section + "_restored")
        with connect(state["database"]) as db:
            # Rebind the immutable ownership marker before post-data installs its guard.
            row = db.execute(
                "SELECT scope,source_config_id,contract_version FROM "
                "public.wave7_synthetic_ownership"
            ).fetchall()
            require(
                row == [(SYNTHETIC_SCOPE, SOURCE_CONFIG_ID, CONTRACT_VERSION)],
                "ownership_scope_mismatch",
            )
            db.execute(
                "UPDATE public.wave7_synthetic_ownership SET database_name=%s,database_oid=%s",
                [state["database"], state["oid"]],
            )
        tools.run(
            "pg_restore",
            state["database"],
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--section=post-data",
            *archive_args,
            input_data=archive_input,
        )
        checkpoint("schema_restored")
        with connect(state["database"]) as db:
            require(
                database_profile(db) == manifest["database_profile"],
                "restored_database_profile_mismatch",
            )
            restored_baseline = baseline(db)
            if restored_baseline != manifest["baseline"]:
                write_file(target / "observed-baseline.json", canonical(restored_baseline))
                changed = [
                    name
                    for name in sorted(
                        set(restored_baseline["tables"]) | set(manifest["baseline"]["tables"])
                    )
                    if restored_baseline["tables"].get(name)
                    != manifest["baseline"]["tables"].get(name)
                ]
                if restored_baseline["sequences"] != manifest["baseline"]["sequences"]:
                    changed.append("sequences")
                raise RecoveryError("restored_baseline_mismatch:" + ",".join(changed))
            require(references(db) == manifest["references"], "restored_references_mismatch")
            require(
                digest(tools.schema(state["database"])) == manifest["schema_sha256"],
                "restored_schema_mismatch",
            )
            for item in manifest["references"]:
                if item["backend"] == BACKEND:
                    store.get(original(item))
        checkpoint("verified")
        # Detect damage to the pinned backup during restoration too.
        verify_bundle(bundle, expected_manifest_sha256, _files=_files)
        # Keep a durable non-READY identity before attempting the completion
        # publication. If its replacement succeeds but directory fsync fails,
        # disk-full must not strand a misleading READY journal or authorize a
        # guessed cleanup target. Replacing this saved record needs no new file.
        write_file(
            target / "ready-publication-failure.json",
            canonical({**state, "state": "FAILED_READY_PUBLICATION"}),
        )
        sync_directory(target)
        state.update(state="READY", private_root=str(store.root))
        journal(target, state)
        return {**state, "target": str(target)}
    except BaseException as exc:
        failed_ready = state["state"] == "READY"
        state["state"] = "FAILED_READY_PUBLICATION" if failed_ready else "FAILED"
        state["failure_code"] = str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__
        try:
            journal(target, state)
        except OSError:
            # Disk-full must not prevent rollback using the last durable identity.
            if failed_ready:
                try:
                    os.replace(target / "ready-publication-failure.json", target / "journal.json")
                    sync_directory(target)
                except OSError:
                    # Storage itself may be unavailable. Never claim readiness
                    # or delete a DB without a readable non-READY identity record.
                    raise RecoveryError("restore_failed_rollback_pending:" + str(target)) from None
        if created:
            # A crash before the durable OID/nonce journal is intentionally manual/quarantined.
            try:
                rollback(target=target, synthetic_fixtures_only=True, offline=True)
            except Exception:
                # No force DROP and no false rollback success; leave original journal/evidence.
                raise RecoveryError("restore_failed_rollback_pending:" + str(target)) from None
        raise RecoveryError(
            "restore_failed_target_quarantined:" + state["failure_code"] + ":" + str(target)
        ) from None
