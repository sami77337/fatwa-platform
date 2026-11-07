"""Supply an existing Wave7 producer receipt to a fresh read-only child."""

import json
import os
import subprocess
import sys
from hashlib import sha256

from apps.fast9_pg_workflow_audit.adapter import window_sha256
from apps.intake_workflow.guards import require_owned_database


def verify_existing_audit(batch, row, event, stored):
    expected = {
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
        "PGDATABASE": "wave7_synthetic_ci",
        "PGTESTDATABASE": "test_wave7_synthetic_ci",
        "PGUSER": "wave7_synthetic",
        "DJANGO_SETTINGS_MODULE": "config.settings.wave7_test",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise AssertionError("Reserved B6 Wave7 profile required")
    owner = require_owned_database(synthetic_fixtures_only=True)
    if owner.database_name != expected["PGTESTDATABASE"]:
        raise AssertionError("Reserved B6 Wave7 test database required")
    # These are the producer's observed bytes, selected response and transition
    # receipt. The child may neither choose a row nor establish its own pins.
    digest = window_sha256(stored)
    args = {
        "database-name": owner.database_name,
        "database-oid": owner.database_oid,
        "batch-id": batch.pk,
        "row-id": row.pk,
        "row-ordinal": row.row_ordinal,
        "payload-sha256": sha256(bytes(batch.original_payload)).hexdigest(),
        "row-sha256": sha256(row.original_row.encode("utf-8")).hexdigest(),
        "latest-event-id": event.event_id,
        "latest-operation-id": event.operation_id,
        "audit-sha256": digest,
    }
    command = [
        sys.executable,
        "-B",
        "-m",
        "tools.fast9_pg_workflow_audit",
        "--synthetic-only",
        "--acceptance",
    ]
    for name, value in args.items():
        command.extend(("--" + name, str(value)))
    child = subprocess.run(command, capture_output=True, text=True, timeout=45)
    report = json.loads(child.stdout)
    counts = report.get("acceptance")
    if (
        child.returncode != 0
        or report.get("status") != "CONNECTED"
        or report.get("reason") != "BOUNDED_SYNTHETIC_READ"
        or report.get("audit_sha256") != digest
        or counts != {"status": "PASS", "run": 7, "failures": 0, "errors": 0, "skipped": 0}
    ):
        raise AssertionError(
            f"FAST9 stored audit refused: {child.returncode}, {report.get('reason')}, {counts}"
        )
    print(
        "FAST9_STORED_AUDIT "
        + json.dumps(
            {
                "database": owner.database_name,
                "oid": owner.database_oid,
                "receipt_sha256": digest,
                "read": report["reason"],
                "acceptance": counts,
            },
            sort_keys=True,
        )
    )
