"""Run only inside a new isolated B6 cluster, never against the host database."""
import os
import sys

sys.path.insert(0, "/site")
from tools.dev.qa import APP_TESTS, run


def main():
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Python 3.13 required")
    if (os.environ.get("PGDATABASE") != "b6_ephemeral"
            or os.environ.get("PGTESTDATABASE") != "test_b6_ephemeral"
            or not os.environ.get("PGHOST", "").startswith("fatwa-b6-")
            or os.environ.get("PGUSER") != "postgres"):
        raise RuntimeError("Refusing a non-B6 database")
    import psycopg
    with psycopg.connect(dbname="b6_ephemeral") as connection:
        version = connection.info.server_version // 10000
        if version != int(sys.argv[1]) or version not in (17, 18):
            raise RuntimeError("Unexpected PostgreSQL version")
        with connection.cursor() as cursor:
            cursor.execute("SELECT datname FROM pg_database WHERE NOT datistemplate")
            if {row[0] for row in cursor.fetchall()} != {"postgres", "b6_ephemeral"}:
                raise RuntimeError("Cluster is not empty and disposable")
    for command in [["check", "--database", "default"], ["makemigrations", "--check", "--dry-run"],
                    ["migrate", "--noinput"], ["migrate", "--check"],
                    ["test", *APP_TESTS, "--noinput", "--verbosity=2"]]:
        run([sys.executable, "manage.py", *command], env=dict(os.environ), timeout=480)


if __name__ == "__main__":
    main()
