"""Run only the offline diagnostics in a helper-owned PostgreSQL environment.

The read-only server-version check records which major actually ran. These are
not database/product acceptance tests and do not initialize application tables.
"""

import os
import unittest

import psycopg

from . import test_evidence


def main():
    expected = os.environ.get("PG_EXPECTED_MAJOR")
    if expected not in {"17", "18"} or os.environ.get("PGHOST") != "127.0.0.1":
        raise SystemExit("OWNED_POSTGRES_HELPER_REQUIRED")
    with psycopg.connect(autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            actual = int(cursor.fetchone()[0])
    if actual // 10000 != int(expected):
        raise SystemExit("POSTGRES_MAJOR_MISMATCH")
    print(f"DIAGNOSTIC_ONLY_POSTGRES_SERVER_VERSION_NUM={actual}", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_evidence)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
