"""Synchronous transaction lifetime checks for the cooperative maintenance gate.

These checks inspect the current Django execution's connection, not other clients
or privileged SQL. They never commit a caller's unfinished work.
"""

from django.db import connections


def unsettled():
    """Return initialized connections with unfinished transactions or callbacks."""
    result = []
    for db in connections.all(initialized_only=True):
        raw = db.connection
        if raw is None or getattr(raw, "closed", False):
            continue
        status = getattr(getattr(raw, "info", None), "transaction_status", None)
        if (
            db.in_atomic_block
            or not db.get_autocommit()
            or db.run_on_commit
            or (status is not None and status.name != "IDLE")
        ):
            result.append(db)
    return result


def require_outer_boundary():
    from .service import require

    # Domain ownership/queue guards support the default alias only. Do not
    # pretend one database-bound control protects a second database.
    require(set(connections) == {"default"}, "maintenance_database_alias_unsupported")
    require(not unsettled(), "maintenance_outer_boundary_required")


def abort_unfinished():
    """Close leaked connections synchronously, rolling back and discarding hooks.

    Django keeps closed_in_transaction until a leaked atomic is unwound; the
    underlying PostgreSQL connection must nevertheless be closed before release.
    Return whether the writer violated the boundary. Never run pending hooks.
    """
    dirty = unsettled()
    for db in dirty:
        raw = db.connection
        try:
            # Await PostgreSQL's ROLLBACK response, not merely TCP socket close.
            # Django.rollback() refuses leaked atomic blocks; this emergency
            # rollback deliberately aborts that malformed unit before closing it.
            raw.rollback()
            if raw.info.transaction_status.name != "IDLE":
                raise RuntimeError("maintenance_transaction_cleanup_failed")
        finally:
            db.close()
        if not raw.closed:
            raise RuntimeError("maintenance_transaction_cleanup_failed")
    return bool(dirty)


# Deliberately small reviewed set. shell/dbshell/flush/loaddata/clearsessions and
# unknown commands are refused even inside an existing admission. Test setup is
# a separate stopped-writer bootstrap, not an operational administration bypass.
SUPPORTED_COMMANDS = frozenset(
    {
        "check",
        "showmigrations",
        "migrate",
        "wave7_intake",
        "wave7_review",
        "import_book622",
        "audit_book622",
        "benchmark_reference",
    }
)


def require_supported_command(command):
    """Fail-fast hook for management dispatchers; this is not an installed hook."""
    from .integration import MaintenanceUnavailable, required

    if required() and (type(command) is not str or command not in SUPPORTED_COMMANDS):
        raise MaintenanceUnavailable("maintenance_management_command_unsupported")


def run_management_command(command, *args, **options):
    """Reviewed call_command replacement, holding admission through command exit."""
    from django.core.management import call_command

    from .integration import mutation_scope

    require_supported_command(command)
    with mutation_scope():
        return call_command(command, *args, **options)
