"""Read an explicitly supplied existing disposable Wave7 audit, without writes."""

import argparse
import json
import os
from dataclasses import asdict
from uuid import UUID


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--database-oid", type=int, required=True)
    for name in ("batch-id", "row-id", "latest-event-id", "latest-operation-id"):
        parser.add_argument("--" + name, type=UUID, required=True)
    parser.add_argument("--row-ordinal", type=int, required=True)
    for name in ("payload-sha256", "row-sha256", "audit-sha256"):
        parser.add_argument("--" + name, required=True)
    args = vars(parser.parse_args(argv))
    args.pop("synthetic_only")
    acceptance = args.pop("acceptance")
    report = {"status": "NOT_RUN", "reason": "EXPLICIT_WAVE7_PROFILE_REQUIRED"}
    try:
        if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings.wave7_test":
            print(json.dumps(report))
            return 3
        import django

        django.setup()
        from django.conf import settings
        from django.db import connections

        from apps.fast9_pg_workflow_audit.adapter import StoredIdentity, read_stored_audit
        from apps.intake_workflow.guards import validate_write_configuration

        # Only a supplied test target. No base fallback, migration/test runner,
        # password search, role creation, fixture import or schema mutation.
        target = validate_write_configuration(synthetic_fixtures_only=True)
        if (
            target.test_name != args["database_name"]
            or settings.WAVE7_TEST_DATABASE_NAME != args["database_name"]
        ):
            report["reason"] = "DATABASE_IDENTITY_MISMATCH"
        elif connections["default"].connection is not None:
            report["reason"] = "FRESH_READ_ONLY_CONNECTION_REQUIRED"
        else:
            connections["default"].settings_dict["NAME"] = args["database_name"]
            connections["default"].settings_dict.setdefault("OPTIONS", {})["options"] = (
                "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000"
            )
            identity = StoredIdentity(**args)
            result = read_stored_audit(identity, synthetic_fixtures_only=True)
            # The command reports technical metadata only; no stored text/events.
            report = asdict(
                result.__class__(result.status, result.reason, audit_sha256=result.audit_sha256)
            )
            if acceptance and result.status == "CONNECTED":
                from tests.fast9_pg_workflow_audit.stored_acceptance import run_acceptance

                report["acceptance"] = run_acceptance(identity)
                if report["acceptance"]["status"] != "PASS":
                    report["status"] = "FAIL"
    except Exception:
        report = {"status": "NOT_RUN", "reason": "READ_UNAVAILABLE"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "CONNECTED" else (1 if report["status"] == "FAIL" else 3)


if __name__ == "__main__":
    raise SystemExit(main())
