"""No DB creation, migration, import, seed, arbitrary origin, or application patch."""

import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def expected_catalog():
    """Public fields of the existing seed_reference_catalog fixed fixture only."""
    from apps.editorial_workbench.services import _asserted_catalog

    headings = _asserted_catalog()
    first = headings[0]
    edition = {
        "id": 7001,
        "edition_key": first.edition_key,
        "title": "طبعة اصطناعية",
        "publisher": "ناشر اصطناعي",
        "heading_count": 3,
        "root_count": 1,
        "max_depth": 2,
        "source_archive_sha256": first.source_archive_sha256,
        "source_input_sha256": first.source_input_sha256,
        "work": {
            "source_namespace": first.source_namespace,
            "source_book_id": "622",
            "title_original": first.work_title,
            "madhhab": "اصطناعي فقط",
        },
    }
    nodes = [
        {
            "id": h.source_row_id,
            "source_id": f"wave7-title-{h.source_row_id}",
            "parent_id": None if h.source_row_id == 1 else 1,
            "title": h.heading_title,
            "depth": 1 if h.source_row_id == 1 else 2,
            "position": 1 if h.source_row_id == 1 else h.source_row_id - 1,
            "source_order": h.source_row_id,
            "children_count": 2 if h.source_row_id == 1 else 0,
            "part": h.printed_part,
            "page": h.printed_page,
            "page_id": h.source_row_id,
            "source_entry_number": None,
        }
        for h in headings
    ]
    return edition, nodes


def fixture_contract():
    from apps.editorial_export.services import build_export
    from apps.editorial_queue.services import build_queue_catalog
    from apps.editorial_search.services import search_catalog

    bundle = build_export(synthetic_fixtures_only=True)
    packets = {
        row["packet"]["identity"]["case_key"]: row["packet"] for row in bundle.report()["cases"]
    }
    catalog = build_queue_catalog()
    query = packets["history"]["snapshots"][0]["title"]
    hits = search_catalog(catalog, q=query, source="draft").hits
    historical = next(
        hit
        for hit in hits
        if hit.case_key == "history" and hit.revision != packets["history"]["selection"]["revision"]
    )
    return {
        "fixture": "existing fixed synthetic export/queue/search services; no owner archives",
        "fixture_sha256": sha256(bundle.file("report.json")).hexdigest(),
        "packets": {key: packets[key] for key in ("history", "batch-synthetic-csv-1")},
        "search": asdict(historical),
        "query": query,
        "files": {name: sha256(payload).hexdigest() for name, payload in bundle.files},
    }


def catalog_preflight():
    """Opt-in to an ALREADY owned/seeded DB; ownership guard executes only SELECTs."""
    if os.environ.get("FAST8_EXISTING_SYNTHETIC_PG") != "1":
        return {"result": "NOT_RUN", "reason": "SYNTHETIC_POSTGRES_NOT_SUPPLIED"}
    from django.db import DatabaseError

    from apps.editorial_workbench.services import _asserted_catalog
    from apps.intake_workflow.guards import SyntheticWriteDenied, require_owned_database
    from apps.reference import services
    from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
    from apps.reference.query import Page
    from apps.reference_links.django_adapter import DjangoCatalog
    from apps.reference_links.resolution import CatalogReadError

    try:
        context = require_owned_database(synthetic_fixtures_only=True)
        # Count before retrieving any text; never browse a mixed-source database.
        if tuple(
            model.objects.count() for model in (ReferenceWork, ReferenceEdition, ReferenceHeading)
        ) != (1, 1, 3):
            return {"result": "FAIL", "reason": "SYNTHETIC_CATALOG_INVENTORY_MISMATCH"}
        edition, nodes = expected_catalog()
        inventory = services.list_books(Page(2))
        if inventory.total != 1 or inventory.items != [edition]:
            return {"result": "FAIL", "reason": "SYNTHETIC_CATALOG_IDENTITY_MISMATCH"}
        actual_edition = services.resolve_edition(7001)
        for node in nodes:
            if services.heading_data(services.node(actual_edition, node["id"])) != node:
                return {"result": "FAIL", "reason": "SYNTHETIC_CATALOG_IDENTITY_MISMATCH"}
        for heading in _asserted_catalog():
            if DjangoCatalog().lookup(heading.edition_id, heading.source_row_id) != (heading,):
                return {"result": "FAIL", "reason": "SYNTHETIC_CATALOG_IDENTITY_MISMATCH"}
    except (SyntheticWriteDenied, CatalogReadError, DatabaseError, services.HeadingNotFound):
        return {"result": "NOT_RUN", "reason": "OWNED_SYNTHETIC_POSTGRES_UNAVAILABLE"}
    return {
        "result": "READY",
        "database": context.database_name,
        "fixture": "wave7-synthetic-toc/7001/rows-1-2-3",
        "archive_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "edition": edition,
        "nodes": nodes,
    }


def bounded_catalog_preflight():
    if os.environ.get("FAST8_EXISTING_SYNTHETIC_PG") != "1":
        return catalog_preflight()
    try:
        child = subprocess.run(
            [sys.executable, "-m", "tools.fast8_browser_conformance.run", "--catalog-preflight"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        if child.returncode != 0:
            return {"result": "FAIL", "reason": "CATALOG_PREFLIGHT_FAILED"}
        return json.loads(child.stdout)
    except subprocess.TimeoutExpired:
        return {"result": "NOT_RUN", "reason": "CATALOG_PREFLIGHT_TIMEOUT"}
    except ValueError:
        return {"result": "FAIL", "reason": "CATALOG_PREFLIGHT_PROTOCOL_FAILED"}


def run():
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    django.setup()
    from tests.acceptance.fastbuild.test_browser import editorial_server

    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
    ).strip()
    dirty = bool(
        subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                "tests/fast8_browser_conformance",
                "tools/fast8_browser_conformance",
            ],
            cwd=ROOT,
            text=True,
            timeout=10,
        ).strip()
    )
    contract = fixture_contract()
    catalog = bounded_catalog_preflight()
    metadata = {
        "tested_sha": revision,
        "owned_paths_dirty": dirty,
        "fixture": contract["fixture"],
        "fixture_sha256": contract["fixture_sha256"],
        "postgresql": catalog,
    }
    node = shutil.which("node")
    if not node:
        return {**metadata, "result": "NOT_RUN", "browser": "NOT_RUN", "reason": "NODE_UNAVAILABLE"}
    # For the DB-free journey even accidental connection attempts are forbidden
    # in the WSGI thread. No fake catalog lookup is substituted.
    guard = (
        nullcontext()
        if catalog["result"] == "READY"
        else patch(
            "django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection",
            side_effect=AssertionError("FAST8_DATABASE_ACCESS_FORBIDDEN"),
        )
    )
    with guard, editorial_server() as origin:
        result = subprocess.run(
            [node, str(Path(__file__).with_name("browser.mjs")), origin],
            input=json.dumps({**contract, "catalog": catalog}),
            env={**os.environ, "FATWA_FASTBUILD_PYTHON": sys.executable},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=100,
            check=False,
        )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert result.returncode == {"PASS": 0, "FAIL": 1, "NOT_RUN": 2}[report["result"]]
    except (ValueError, IndexError, KeyError, AssertionError):
        return {
            **metadata,
            "result": "FAIL",
            "browser": "FAIL",
            "reason": "HARNESS_PROTOCOL_FAILED",
        }
    return {**metadata, **report}


def main():
    try:
        report = run()
    except subprocess.TimeoutExpired:
        report = {"result": "FAIL", "reason": "HARNESS_DEADLINE_EXCEEDED"}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return {"PASS": 0, "FAIL": 1, "NOT_RUN": 2}[report["result"]]


if __name__ == "__main__":
    if sys.argv[1:] == ["--catalog-preflight"]:
        import django

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        django.setup()
        print(json.dumps(catalog_preflight(), ensure_ascii=True))
    else:
        sys.exit(main())
