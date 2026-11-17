"""Durable cooperative maintenance gate for synthetic writes and storage GC.

Integrators must hold mutation_guard BEFORE filesystem/DB locks until the outer
transaction commits and file bindings finish. A status check alone is not a guard.
Linux local-filesystem contract; no OS security settings or shared app edits.
"""

import json
import os
import secrets
import stat
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

from .leases import Lease, execution
from .service import RecoveryError, connect, guard, journal, read_file, require, safe_directory

FORMAT = "fatwa-maintenance-v1"
_LEASE = ContextVar("platform_mutation_lease", default=())


def _root(root):
    root = root if root is not None else getattr(settings, "FATWA_RECOVERY_MAINTENANCE_ROOT", None)
    require(root is not None, "maintenance_unconfigured")
    return safe_directory(root)


@contextmanager
def _lock(root, name, *, shared=False):
    import fcntl

    fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o600,
            "maintenance_lock_invalid",
        )
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryError("maintenance_busy") from None
        yield
    finally:
        os.close(fd)


def _identity():
    owned = guard(synthetic_fixtures_only=True, offline=True)
    with connect() as db:
        cluster = str(db.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
    return {"database": owned.database_name, "oid": owned.database_oid, "cluster": cluster}


def _read(root):
    state = json.loads(read_file(root / "journal.json"))
    require(
        state.get("format") == FORMAT and state.get("binding") == _identity(),
        "maintenance_binding_mismatch",
    )
    require(state.get("phase") in {"ACTIVE", "DRAINING", "FROZEN"}, "maintenance_state_invalid")
    return state


def initialize(*, root, storage, synthetic_fixtures_only=False):
    require(synthetic_fixtures_only is True, "synthetic_ack_required")
    root = _root(root)
    from apps.private_media.filesystem import FileSystemStorage

    require(isinstance(storage, FileSystemStorage), "filesystem_adapter_required")
    private_root = str(safe_directory(storage.root))
    # An existing initialization is checked and never reset to ACTIVE.
    if (root / "journal.json").exists():
        state = _read(root)
        require(state["private_root"] == private_root, "maintenance_storage_mismatch")
        return status(root=root)
    require(not os.listdir(root), "maintenance_directory_not_empty")
    state = {
        "format": FORMAT,
        "binding": _identity(),
        "private_root": private_root,
        "phase": "ACTIVE",
        "generation": secrets.token_hex(16),
    }
    with _lock(root, "admin.lock"), _lock(root, "activity.lock"):
        require(not (root / "journal.json").exists(), "maintenance_already_initialized")
        journal(root, state)
    return status(root=root)


def status(*, root=None):
    state = _read(_root(root))
    return {
        "phase": state["phase"],
        "generation": state["generation"],
        "writes_allowed": state["phase"] == "ACTIVE",
    }


def enter(*, root=None, synthetic_fixtures_only=False):
    """Deny new entrants first, then drain current mutation leases without killing any."""
    require(synthetic_fixtures_only is True, "synthetic_ack_required")
    root = _root(root)
    with _lock(root, "admin.lock"):
        state = _read(root)
        if state["phase"] == "ACTIVE":
            state.update(phase="DRAINING", generation=secrets.token_hex(16))
            journal(root, state)
        try:
            with _lock(root, "activity.lock"):
                if state["phase"] != "FROZEN":
                    state["phase"] = "FROZEN"
                    journal(root, state)
        except RecoveryError as exc:
            if str(exc) != "maintenance_busy":
                raise
        return {"phase": state["phase"], "generation": state["generation"], "writes_allowed": False}


def resume(*, root=None, expected_generation, confirmed=False, synthetic_fixtures_only=False):
    require(synthetic_fixtures_only is True and confirmed is True, "explicit_resume_required")
    root = _root(root)
    with _lock(root, "admin.lock"), _lock(root, "activity.lock"):
        state = _read(root)
        require(
            state["phase"] in {"DRAINING", "FROZEN"} and state["generation"] == expected_generation,
            "maintenance_generation_mismatch",
        )
        state.update(phase="ACTIVE", generation=secrets.token_hex(16))
        journal(root, state)
    return status(root=root)


@contextmanager
def mutation_guard(*, root=None, operation="WRITE", synthetic_fixtures_only=False):
    """Wrap the entire synchronous write or GC unit, including outer commit.

    Reentrant within the same synchronous task; never pass a live lease to another
    thread/task. Missing/invalid control state fails closed. Do not use after
    entering transaction.atomic() or a V9 binding lock.
    """
    require(
        synthetic_fixtures_only is True and operation in {"WRITE", "GC"}, "mutation_guard_required"
    )
    root = _root(root)
    held = _LEASE.get()
    if any(lease.matches(root) for lease in held):
        yield
        return
    with _lock(root, "activity.lock", shared=True):
        state = _read(root)
        require(state["phase"] == "ACTIVE", "maintenance_writes_blocked")
        lease = Lease(str(root), execution())
        token = _LEASE.set((*held, lease))
        try:
            yield
        finally:
            lease.active = False
            _LEASE.reset(token)


@contextmanager
def frozen(*, root, storage):
    """Keep maintenance FROZEN throughout capture/encryption; resume cannot race it."""
    root = _root(root)
    with _lock(root, "admin.lock"), _lock(root, "activity.lock"):
        state = _read(root)
        require(state["phase"] == "FROZEN", "maintenance_not_frozen")
        require(
            state["private_root"] == str(safe_directory(storage.root)),
            "maintenance_storage_mismatch",
        )
        yield state["generation"]
