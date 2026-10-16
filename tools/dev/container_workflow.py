"""Offline Python 3.13 worker for the existing isolated development cluster only."""

import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ARCHIVE = Path("/source/book622.zip")
MAPPED = "b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7"
INPUT_SHA = "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14"
REPORT = {"REAL_SOURCE_DATABASE_IMPORT": "NOT_RUN", "tests": {}}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def bootstrap():
    require(sys.version_info[:2] == (3, 13), "Python 3.13 is required")
    require(os.environ.get("FATWA_PRODUCTION", "0") == "0", "Production is forbidden")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-cache-dir",
            "--no-deps",
            "--disable-pip-version-check",
            "--no-compile",
            "--find-links=/wheels",
            "--target=/tmp/fatwa-packages",
            "-r",
            "/site/requirements.txt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, "Offline runtime wheel installation failed")
    sys.path[:0] = ["/site", "/tmp/fatwa-packages"]
    os.environ.update(
        DJANGO_SETTINGS_MODULE="config.settings.development",
        PYTHONDONTWRITEBYTECODE="1",
        FATWA_PRODUCTION="0",
    )
    # Credential remains a read-only file mount; never a Docker environment setting.
    require(os.environ.get("PGDATABASE") == "fatwa_reference", "Wrong development DB")
    require(os.environ.get("PGUSER") == "fatwa_app", "Only fatwa_app is permitted")
    require(os.environ.get("PGPORT") == "5432", "Unexpected PostgreSQL port")
    os.environ["PGPASSWORD"] = Path("/run/secrets/app-password").read_text().rstrip("\r\n")
    import django

    django.setup()


def command_json(**options):
    from django.core.management import call_command

    output = io.StringIO()
    call_command("import_book622", archive=str(ARCHIVE), stdout=output, **options)
    return json.loads(output.getvalue())


def validate_report(report):
    require(report["valid"] is True and not report["issues"], "S1 source validation failed")
    require(report["unique_valid_records"] == 11397, "Wrong source heading count")
    require(
        (report["roots"], report["max_depth"], report["reachable_nodes"]) == (32, 5, 11397),
        "Wrong source hierarchy",
    )
    require(report["exact_original_id_title_matches"] == 11397, "Original titles differ")
    require(report["inferred_titles"] == 0, "Inferred titles are forbidden")
    require(report["mapped_checksum"] == MAPPED, "Mapped source checksum changed")
    require(report["input_sha256"] == INPUT_SHA, "Input member checksum changed")


def read_state(prepared):
    from django.db import connection, transaction
    from django.db.models import Max

    from apps.reference.ingest import ingest_catalog
    from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(
                "SELECT current_database(), current_user, current_setting('server_version_num')::int"
            )
            database, role, version = cursor.fetchone()
            require(
                database == "fatwa_reference" and role == "fatwa_app", "Wrong database identity"
            )
            require(180000 <= version < 190000, "Expected the existing PostgreSQL 18 cluster")
            cursor.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            require(not any(cursor.fetchone()), "Application role has unexpected privileges")
        editions = list(ReferenceEdition.objects.select_related("work"))
        require(len(editions) <= 1, "Conflicting snapshots exist; refusing import")
        if editions:
            edition = editions[0]
            require(
                edition.edition_key == prepared.spec.edition_key
                and edition.work.source_namespace == "shamela"
                and edition.work.source_book_id == "622",
                "Conflicting source edition exists",
            )
        else:
            require(ReferenceHeading.objects.count() == 0, "Orphan/conflicting catalog rows exist")
        for work in ReferenceWork.objects.all():
            require(
                work.source_namespace == "shamela" and work.source_book_id == "622",
                "Another source work exists; refusing import",
            )
        # This is the existing S1 -> S0 management-command PREVIEW, in a read-only transaction.
        preview = command_json()
        validate_report(preview)
        persistence = preview["persistence"]
        require(
            persistence["dry_run"]
            and persistence["checksum"] == MAPPED
            and persistence["heading_count"] == 11397,
            "Invalid persistence preview",
        )
        # ingest_catalog preview compares all original fields, parents and normalized titles.
        checked = ingest_catalog(prepared.spec, prepared.records)
        require(asdict(checked) == persistence, "Preview results disagree")
        counts = {
            "headings": ReferenceHeading.objects.count(),
            "roots": ReferenceHeading.objects.filter(parent__isnull=True).count(),
            "max_depth": ReferenceHeading.objects.aggregate(value=Max("depth"))["value"],
        }
        if editions:
            require(
                counts == {"headings": 11397, "roots": 32, "max_depth": 5},
                "Existing snapshot is incomplete",
            )
            require(persistence["unchanged"] is True, "Existing snapshot disagrees")
        return {
            "database": database,
            "role": role,
            "server_version_num": version,
            "counts": counts,
            "preview": persistence,
        }


def accept_source():
    from django.core.management import call_command

    from tools.fiqh_import.book622 import validate_book622

    output = io.StringIO()
    call_command("check", databases=["default"], stdout=output)
    call_command("migrate", check_unapplied=True, stdout=output)
    validation = command_json(validate_only=True)
    validate_report(validation)
    prepared, _ = validate_book622(ARCHIVE)
    REPORT["source"] = {
        key: validation[key]
        for key in (
            "source_archive_sha256",
            "input_sha256",
            "mapped_checksum",
            "exact_original_id_title_matches",
            "inferred_titles",
        )
    }
    before = read_state(prepared)
    REPORT["before"] = before
    if before["preview"]["unchanged"]:
        REPORT["import_action"] = "ALREADY_COMPLETE_READ_ONLY"
    else:
        applied = command_json(apply=True, expected_checksum=before["preview"]["checksum"])
        validate_report(applied)
        require(applied["database_import"] in ("IMPORTED", "UNCHANGED"), "Import did not complete")
        REPORT["import_action"] = applied["database_import"]
    after = read_state(prepared)
    require(after["preview"]["unchanged"], "Read-only post-import comparison failed")
    REPORT["after"] = after
    REPORT["REAL_SOURCE_DATABASE_IMPORT"] = "PASS"
    # Only a few public headings go to the host for HTTP comparison; no source export.
    samples = [next(row for row in prepared.records if row.depth == depth) for depth in (1, 2, 5)]
    by_id = {row.source_row_id: row for row in prepared.records}
    probes = []
    for row in samples:
        chain = [row]
        while chain[0].parent_source_row_id is not None:
            chain.insert(0, by_id[chain[0].parent_source_row_id])
        probes.append(
            {
                "id": row.source_row_id,
                "source_id": row.source_id,
                "title": row.title_original,
                "parent_id": row.parent_source_row_id,
                "depth": row.depth,
                "part": row.source_part,
                "page": row.source_page_number,
                "page_id": row.source_page_id,
                "source_entry_number": row.source_entry_number,
                "path": [item.source_row_id for item in chain],
            }
        )
    REPORT["_probes"] = probes
    REPORT["edition_id"] = after["preview"]["edition_id"]


def run_suite(label, arguments, cwd="/site"):
    env = {
        **os.environ,
        "PYTHONPATH": "/tmp/fatwa-packages:/site",
        "FATWA_622_ARCHIVE": str(ARCHIVE),
    }
    result = subprocess.run(
        [sys.executable, *arguments], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    REPORT["tests"][label] = {
        "result": "PASS" if result.returncode == 0 else "FAIL",
        "output": (result.stdout + result.stderr)[-16000:],
    }


def tests():
    import psycopg

    # S1 uses scratch paths beside its fixtures. Copy only code/test resources into tmpfs.
    scratch = Path("/tmp/fiqh-suite")
    for relative in ("tools/fiqh_import", "tests/fiqh_import", "docs/data-ingest"):
        shutil.copytree(
            Path("/site") / relative,
            scratch / relative,
            ignore=shutil.ignore_patterns("__pycache__", ".scratch"),
        )
    run_suite(
        "S1_unit_and_real_source",
        ["-m", "unittest", "discover", "-s", "tests/fiqh_import", "-v"],
        str(scratch),
    )
    # Never create, drop, reset, or run tests against fatwa_reference.
    test_db = "test_fatwa_reference_dev"
    try:
        with psycopg.connect(
            dbname=test_db,
            user="fatwa_app",
            password=os.environ["PGPASSWORD"],
            host=os.environ["PGHOST"],
            port=5432,
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=3000",
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                require(cursor.fetchone() == (test_db, "fatwa_app"), "Wrong test database")
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                tables = {row[0] for row in cursor.fetchall()}
                allowed = {
                    "django_migrations",
                    "reference_referencework",
                    "reference_referenceedition",
                    "reference_referenceheading",
                }
                require(tables <= allowed, "Test DB has unexpected tables")
                for table in tables - {"django_migrations"}:
                    # Table comes from the explicit allowlist above, never user input.
                    cursor.execute('SELECT count(*) FROM "' + table + '"')
                    require(cursor.fetchone()[0] == 0, "Test DB is not empty; refusing to touch it")
    except (psycopg.Error, RuntimeError):
        REPORT["tests"]["Django_PostgreSQL"] = {
            "result": "NOT_RUN",
            "blocker": "An accessible empty dedicated test_fatwa_reference_dev database is required; none was created or reset",
        }
        return
    os.environ["PGTESTDATABASE"] = test_db
    run_suite(
        "Django_PostgreSQL",
        [
            "manage.py",
            "test",
            "tests/reference",
            "tests/integration",
            "--settings=config.settings.test",
            "--keepdb",
            "--noinput",
            "--verbosity=2",
        ],
    )


def main():
    phase = "bootstrap"
    try:
        bootstrap()
        phase = "source_preview_apply_verify"
        accept_source()
        phase = "tests"
        tests()
    except (Exception, SystemExit) as error:
        if REPORT["REAL_SOURCE_DATABASE_IMPORT"] != "PASS":
            REPORT["REAL_SOURCE_DATABASE_IMPORT"] = "FAIL"
        message = str(error)
        secret = os.environ.get("PGPASSWORD")
        if secret:
            message = message.replace(secret, "[REDACTED]")
        REPORT["blocker"] = {
            "phase": phase,
            "type": type(error).__name__,
            "message": message[:1500],
        }
    finally:
        # Any test output is also redacted before returning it to the host.
        output = json.dumps(REPORT, ensure_ascii=False)
        secret = os.environ.get("PGPASSWORD")
        if secret:
            output = output.replace(secret, "[REDACTED]")
        print(output)
    return 0 if REPORT["REAL_SOURCE_DATABASE_IMPORT"] == "PASS" and "blocker" not in REPORT else 1


if __name__ == "__main__":
    sys.exit(main())
