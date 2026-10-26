"""python -B -m tools.fast9_pg_browser_catalog.run [--postgres]."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from . import database as db

ROOT = Path(__file__).resolve().parents[2]
EXIT = {"PASS": 0, "FAIL": 1, "NOT_RUN": 2}


def aggregate(report):
    required = ("browser", "catalog", "database_unchanged", "teardown")
    states = [report.get(key, "NOT_RUN") for key in required]
    if "FAIL" in states:
        return "FAIL"
    return "PASS" if all(value == "PASS" for value in states) else "NOT_RUN"


def decode(child):
    try:
        value = json.loads(child.stdout.strip().splitlines()[-1])
        if child.returncode != EXIT[value["result"]]:
            raise ValueError
        if value.get("browser") not in EXIT or value.get("cleanup", {}).get("result") != "PASS":
            raise ValueError
        if value["result"] == "FAIL" and value["browser"] != "FAIL":
            raise ValueError
        if value["result"] == "PASS" and value["browser"] != "PASS":
            raise ValueError
        if "catalog" in value:
            catalog = value["catalog"]["result"]
            expected = (
                "FAIL"
                if "FAIL" in (value["browser"], catalog)
                else "PASS"
                if (value["browser"], catalog) == ("PASS", "PASS")
                else "NOT_RUN"
            )
            if value["result"] != expected:
                raise ValueError
        elif value["result"] != value["browser"]:
            raise ValueError
        return value
    except (ValueError, IndexError, KeyError, TypeError, AttributeError):
        return {"result": "FAIL", "browser": "FAIL", "reason": "BROWSER_PROTOCOL_FAILED"}


@contextmanager
def server():
    """Close WSGI-thread DB connections before join and test database teardown."""
    import threading
    from wsgiref.simple_server import make_server

    from django.core.handlers.wsgi import WSGIHandler
    from django.db import connections

    from tests.acceptance.fastbuild.test_browser import QuietHandler

    with make_server("127.0.0.1", 0, WSGIHandler(), handler_class=QuietHandler) as httpd:

        def serve():
            try:
                httpd.serve_forever()
            finally:
                connections.close_all()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_port}"
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
            if thread.is_alive():
                raise AssertionError("WSGI_TEARDOWN_FAILED")


def browsers(catalog):
    from tools.fast8_browser_conformance.run import fixture_contract

    node = shutil.which("node")
    if not node:
        return {"browser": "NOT_RUN", "catalog": "NOT_RUN", "reason": "NODE_UNAVAILABLE"}
    contract = {**fixture_contract(), "catalog": catalog}
    results = []
    with server() as origin:
        for script in (
            Path(__file__).with_name("operator.mjs"),
            ROOT / "tools/fast8_browser_conformance/browser.mjs",
        ):
            child = subprocess.run(
                [node, str(script), origin],
                input=json.dumps(contract),
                cwd=ROOT,
                env={**os.environ, "FATWA_FASTBUILD_PYTHON": sys.executable},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=110,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = decode(child)
            results.append(result)
            if result["browser"] != "PASS":
                break
    return {
        "browser": "PASS"
        if len(results) == 2 and all(r["browser"] == "PASS" for r in results)
        else results[-1]["browser"],
        "catalog": results[-1].get("catalog", {}).get("result", "NOT_RUN"),
        "journeys": results,
        "fixture_sha256": contract["fixture_sha256"],
    }


def browser_only():
    # Do not honor FAST8's looser existing-database opt-in. Even accidentally
    # attempted DB access in a WSGI thread is forbidden; no catalog double.
    with patch(
        "django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection",
        side_effect=AssertionError("FAST9_DATABASE_ACCESS_FORBIDDEN"),
    ):
        return browsers({"result": "NOT_RUN", "reason": "DISPOSABLE_POSTGRES_NOT_SUPPLIED"})


def postgres(report):
    from django.db import connections

    from apps.intake_workflow.fixtures import seed_reference_catalog
    from apps.intake_workflow.guards import SyntheticWriteDenied
    from tests.wave7_foundation.runner import Wave7TestRunner
    from tools.fast8_browser_conformance.run import catalog_preflight

    runner = Wave7TestRunner(verbosity=0, interactive=False, keepdb=False, parallel=1)
    configured = False
    old = None
    base_before = None
    try:
        db.identity(db.BASE)
        db.empty_application()
        db.vacant_test_name()
        base_before = db.fingerprint()
        runner.setup_test_environment()
        configured = True
        # The only DB create/migrate/drop path is this pre-existing trusted runner.
        old = runner.setup_databases()
        if runner._wave7_created != db.TEST:
            raise AssertionError("TRUSTED_RUNNER_RESOURCE_MISMATCH")
        db.identity(db.TEST)
        db.empty_application()
        seed_reference_catalog(synthetic_fixtures_only=True)
        with patch.dict(os.environ, {"FAST8_EXISTING_SYNTHETIC_PG": "1"}):
            catalog = catalog_preflight()
        if catalog["result"] != "READY":
            raise AssertionError("EXACT_SYNTHETIC_CATALOG_NOT_READY")
        before = db.fingerprint()
        try:
            with db.read_only_connections():
                report.update(browsers(catalog))
        finally:
            connections.close_all()
            db.identity(db.TEST)
            after = db.fingerprint()
            report["database_unchanged"] = "PASS" if before == after else "FAIL"
            report["database_fingerprint"] = {"before": before, "after": after}
            db.assert_unchanged(before, after)
    except db.NotRun as error:
        report.update(catalog="FAIL" if old is not None else "NOT_RUN", reason=str(error))
    except SyntheticWriteDenied:
        report.update(
            catalog="FAIL" if old is not None else "NOT_RUN",
            reason="OWNED_SYNTHETIC_POSTGRES_UNAVAILABLE",
        )
    except Exception:
        # No SQL, credentials, arbitrary exceptions or real data in public output.
        report.update(catalog="FAIL", reason="POSTGRES_ACCEPTANCE_FAILED")
    finally:
        try:
            if old is not None:
                connections.close_all()
                runner.teardown_databases(old)
                db.verify_dropped()
                db.assert_unchanged(base_before, db.fingerprint())
                report["teardown"] = "PASS"
            elif getattr(runner, "_wave7_created", None) is not None:
                # Failed setup may have failed cleanup; do not claim deletion.
                report["teardown"] = "FAIL"
        except Exception:
            report["teardown"] = "FAIL"
        finally:
            if configured:
                runner.teardown_test_environment()
            connections.close_all()


def run(use_postgres=False):
    report = {
        "browser": "NOT_RUN",
        "catalog": "NOT_RUN",
        "database_unchanged": "NOT_RUN",
        "teardown": "NOT_RUN",
        "source_owner_acceptance": "NOT_RUN",
        "policy_connection": "NOT_CONNECTED",
        "revision_timestamps": "NOT_SUPPLIED",
    }
    report["tested_sha"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
    ).strip()
    report["owned_paths_dirty"] = bool(
        subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                "tools/fast9_pg_browser_catalog",
                "tests/fast9_pg_browser_catalog",
            ],
            cwd=ROOT,
            text=True,
            timeout=10,
        ).strip()
    )
    try:
        if use_postgres:
            db.authorize(os.environ)
        else:
            if (
                os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.test")
                != "config.settings.test"
            ):
                raise db.NotRun("BROWSER_ONLY_REQUIRES_TEST_SETTINGS")
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        import django

        django.setup()
        if use_postgres:
            postgres(report)
        else:
            report.update(browser_only())
    except db.NotRun as error:
        report["reason"] = str(error)
    except Exception:
        report.update(browser="FAIL", reason="HARNESS_FAILED")
    report["result"] = aggregate(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    report = run(args.postgres)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return EXIT[report["result"]]


if __name__ == "__main__":
    sys.exit(main())
