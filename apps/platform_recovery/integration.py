"""Application admission for V11; leases surround native commit boundaries, not new atomics.

The flag is an explicit integration opt-in. Administration (capture/restore) does
not use application admission. Only proven fresh-target file restoration has a
separate, exact-root storage scope; it never admits source database writers.
"""

import inspect
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.db import connection

from .leases import Lease, execution

_ADMISSION = ContextVar("recovery_application_admission", default=None)
_RESTORE_FILES = ContextVar("recovery_target_files", default=None)


class MaintenanceUnavailable(RuntimeError):
    """Fixed denial codes only; HTTP callers receive one closed maintenance response."""


@dataclass
class Admission:
    lease: Lease
    database_target: tuple
    private_root: str


def required():
    return getattr(settings, "FATWA_RECOVERY_MAINTENANCE_REQUIRED", False) is True


def _configured_root():
    value = getattr(settings, "FATWA_RECOVERY_MAINTENANCE_ROOT", None)
    if not isinstance(value, (str, Path)) or not str(value):
        raise MaintenanceUnavailable("maintenance_unconfigured")
    return Path(value)


def _database_target():
    return tuple(
        str(connection.settings_dict.get(key, ""))
        for key in ("ENGINE", "HOST", "PORT", "NAME", "USER")
    )


def _current():
    admission = _ADMISSION.get()
    if admission is None or not admission.lease.matches(_configured_root()):
        return None
    if _database_target() != admission.database_target:
        raise MaintenanceUnavailable("maintenance_database_changed")
    return admission


def require_admission():
    """Fail closed for missed entrypoints, including the nested queue-unit fast path."""
    if required() and _current() is None:
        raise MaintenanceUnavailable("maintenance_service_boundary_required")


def _storage_match(admission, root):
    if root is not None and str(Path(root)) != admission.private_root:
        raise MaintenanceUnavailable("maintenance_storage_mismatch")


@contextmanager
def mutation_scope(*, operation="WRITE", storage_root=None):
    if not required():
        yield
        return
    if type(operation) is not str or operation not in {"WRITE", "GC"}:
        raise MaintenanceUnavailable("maintenance_operation_unsupported")
    current = _current()
    if current is not None:
        _storage_match(current, storage_root)
        yield
        return
    from .admission import require_outer_boundary
    from .service import RecoveryError

    try:
        require_outer_boundary()
    except RecoveryError as exc:
        raise MaintenanceUnavailable(str(exc)) from exc
    except Exception as exc:
        raise MaintenanceUnavailable("maintenance_unavailable") from exc
    from . import maintenance
    from .service import read_file

    root = _configured_root()
    entered = False
    try:
        with maintenance.mutation_guard(
            root=root, operation=operation, synthetic_fixtures_only=True
        ):
            state = json.loads(read_file(root / "journal.json"))
            admission = Admission(
                Lease(str(root), execution()),
                _database_target(),
                state["private_root"],
            )
            _storage_match(admission, storage_root)
            configured = getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)
            if configured is not None and hasattr(configured, "root"):
                _storage_match(admission, configured.root)
            token = _ADMISSION.set(admission)
            try:
                entered = True
                yield
                # The low-level guard checks *every* exit, including exceptions,
                # closes leaked transactions before release and discards hooks.
            finally:
                admission.lease.active = False
                _ADMISSION.reset(token)
    except MaintenanceUnavailable:
        raise
    except Exception as exc:
        if str(exc) in {
            "maintenance_unclosed_transaction",
            "maintenance_transaction_cleanup_failed",
        }:
            raise MaintenanceUnavailable(str(exc)) from exc
        if entered:
            raise  # Preserve domain failures after admission; never rewrite them.
        raise MaintenanceUnavailable("maintenance_unavailable") from exc


def mutation_service(function):
    """Decorate ordinary synchronous public service calls outside all native locks."""

    @wraps(function)
    def guarded(*args, **kwargs):
        with mutation_scope():
            value = function(*args, **kwargs)
            if required() and (
                inspect.isawaitable(value)
                or inspect.isgenerator(value)
                or inspect.isasyncgen(value)
            ):
                if hasattr(value, "close"):
                    value.close()
                raise MaintenanceUnavailable("maintenance_deferred_work_unsupported")
            return value

    return guarded


def mutation_context(function):
    """Outermost decorator for a contextmanager; holds through its __exit__/commit."""

    @wraps(function)
    @contextmanager
    def guarded(*args, **kwargs):
        with mutation_scope():
            with function(*args, **kwargs) as value:
                yield value

    return guarded


@contextmanager
def storage_scope(root, *, operation="WRITE"):
    offline = _RESTORE_FILES.get()
    if required() and offline is not None and offline.matches(root):
        if operation != "WRITE":
            raise MaintenanceUnavailable("maintenance_restore_write_only")
        yield
        return
    with mutation_scope(operation=operation, storage_root=root):
        yield


@contextmanager
def offline_restore_files(*, target, state):
    """Only a live, nonce/OID-proven fresh restore may write its own private root.

    This does not set application admission and cannot bypass DB write guards.
    It is called after the recovery journal records the exclusively created DB.
    """
    if not required():
        yield
        return
    from . import service

    target = service.safe_directory(target)
    service.require(
        any(lease.matches(target) for lease in service._TARGET_LEASE.get()),
        "restore_operation_lease_required",
    )
    saved = json.loads(service.read_file(target / "journal.json"))
    service.require(
        saved == state
        and state.get("state") == "RESTORING"
        and service.TARGET.fullmatch(state.get("database", ""))
        and service.NONCE.fullmatch(state.get("nonce", "")),
        "restore_file_scope_invalid",
    )
    with service.connect() as db:
        row = db.execute(
            "SELECT oid,shobj_description(oid,'pg_database'),pg_get_userbyid(datdba) "
            "FROM pg_database WHERE datname=%s",
            [state["database"]],
        ).fetchone()
    service.require(
        row == (state["oid"], state["nonce"], "wave7_synthetic"), "restore_file_identity_mismatch"
    )
    private = target / "private"
    service.require(not private.exists(), "restore_private_target_not_fresh")
    lease = Lease(str(private), execution())
    token = _RESTORE_FILES.set(lease)
    try:
        yield
    finally:
        lease.active = False
        _RESTORE_FILES.reset(token)
