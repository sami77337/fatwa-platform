"""Fail-closed read-only PostgreSQL snapshot for developer QA commands."""

from contextlib import contextmanager

from django.db import connection, transaction


class ReadOnlySnapshotError(ValueError):
    pass


@contextmanager
def read_only_snapshot():
    """No outer transaction, row locks, DDL, import, or repair is permitted.

    PostgreSQL enforces READ ONLY. Repeatable read keeps metadata, rows and citation
    queries in one snapshot even if another development process changes the edition.
    """
    if connection.vendor != "postgresql":
        raise ReadOnlySnapshotError("Requires real PostgreSQL 17/18")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ReadOnlySnapshotError("Requires a fresh transaction; nested audit refused")
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            # Must be the first statement in this transaction, before any ORM read.
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise ReadOnlySnapshotError("PostgreSQL did not confirm READ ONLY")
        if not 170000 <= connection.pg_version < 190000:
            raise ReadOnlySnapshotError("Requires real PostgreSQL 17/18")
        yield connection
