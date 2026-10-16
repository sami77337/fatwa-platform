"""Read-only A6 test-target preflight. This module never launches Django tests.

A separate name or --keepdb does not isolate destructive test setup/teardown.
Even successful preflight is evidence only, not permission to execute tests.
No database, role, grant, schema, volume, or credential is created or changed.
"""

import argparse
import json
import os
import re
from pathlib import Path


class IsolationError(RuntimeError):
    """A fixed, non-sensitive explanation safe to include in a report."""


def require(condition, message):
    if not condition:
        raise IsolationError(message)


def candidate_settings(environment):
    """Reject protected/ambiguous targets before importing a database driver."""
    require(environment.get("PGHOST") == "127.0.0.1", "Candidate must use literal IPv4 loopback")
    port = environment.get("PGPORT", "")
    require(port.isdecimal(), "An explicit candidate port is required")
    require(1024 <= int(port) <= 65535 and int(port) not in (5432, 55432, 8000),
            "Candidate cannot use the protected database or site ports")
    name = environment.get("PGDATABASE", "")
    require(re.fullmatch(r"test_fatwa_a6_[a-f0-9]{12}", name) is not None,
            "A dedicated disposable A6 database name is required")
    require(environment.get("PGUSER") == "fatwa_a6_test", "A dedicated test-only role is required")
    require(not any(environment.get(key) for key in (
        "DATABASE_URL", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGPASSWORD",
        "PGHOSTADDR", "PGPASSFILE", "PGSSLMODE",
    )), "Inherited DSN, credentials, service, or connection overrides are forbidden")
    secret_file = environment.get("FATWA_A6_TEST_PASSWORD_FILE", "")
    require(bool(secret_file), "A test-only credential file is required; live credentials are forbidden")
    return {
        "host": "127.0.0.1", "port": int(port), "dbname": name, "user": "fatwa_a6_test",
        "connect_timeout": 3,
        "options": "-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=1000",
    }, Path(secret_file)


def inspect_candidate(connection, expected_name):
    """Only SELECTs, using a connection forced read-only at connection startup."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, current_setting('server_version_num')::int")
        name, role, version = cursor.fetchone()
        require(name == expected_name and role == "fatwa_a6_test", "Candidate identity mismatch")
        require(180000 <= version < 190000, "Candidate must use PostgreSQL 18")
        cursor.execute("SELECT datname FROM pg_database WHERE NOT datistemplate")
        databases = {row[0] for row in cursor.fetchall()}
        require(databases <= {"postgres", expected_name} and expected_name in databases,
                "Candidate must be a separate cluster without the live catalog or other databases")
        cursor.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        require(not any(cursor.fetchone()), "Candidate role has administrative privileges")
        cursor.execute(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
        )
        require(not cursor.fetchall(), "Candidate must be empty; no cleanup will be attempted")
    return {"preflight": "PASS", "django_postgresql_tests": "NOT_RUN",
            "scope": "Read-only candidate identity and emptiness; no test setup or teardown executed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true", required=True)
    parser.parse_args(argv)
    report = {"preflight": "NOT_RUN", "django_postgresql_tests": "NOT_RUN"}
    try:
        options, secret_file = candidate_settings(os.environ)
        # This never falls back to the live role/credential or to fatwa_reference.
        import psycopg

        password = secret_file.read_text(encoding="utf-8").rstrip("\r\n")
        require(bool(password), "Test credential file is empty")
        with psycopg.connect(**options, password=password) as connection:
            report = inspect_candidate(connection, options["dbname"])
    except IsolationError as error:
        report["blocker"] = str(error)
    except Exception:
        # Driver and filesystem exceptions may contain credentials/DSNs; omit them.
        report["blocker"] = "Candidate preflight unavailable; no raw connection details retained"
    print(json.dumps(report))
    return 0 if report["preflight"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
