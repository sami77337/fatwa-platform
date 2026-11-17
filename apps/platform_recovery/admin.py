"""Read-only restore inspection and explicit nonce-proven quarantine reconciliation."""

import json

from . import service


def _inspect(target):
    state = json.loads(service.read_file(target / "journal.json"))
    service.require(
        state.get("format") == service.FORMAT
        and service.TARGET.fullmatch(state.get("database", "")),
        "restore_record_invalid",
    )
    service.require(
        type(state.get("nonce")) is str and service.NONCE.fullmatch(state["nonce"]),
        "restore_record_invalid",
    )
    with service.connect() as db:
        row = db.execute(
            "SELECT oid,shobj_description(oid,'pg_database'), "
            "pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s",
            [state["database"]],
        ).fetchone()
        cluster = str(db.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
    if state["state"] == "READY":
        valid = row is not None and row == (state["oid"], state["nonce"], "wave7_synthetic")
        status, action = (
            ("READY_RECORDED", "PRESERVE") if valid else ("UNKNOWN_PRESERVED", "MANUAL_INSPECTION")
        )
    elif row is None:
        status, action = "DATABASE_ABSENT", "RECORD_ROLLBACK"
    elif row[1] != state.get("nonce") or row[2] != "wave7_synthetic":
        status, action = "UNKNOWN_PRESERVED", "MANUAL_INSPECTION"
    elif state.get("oid") is None:
        status, action = "IDENTITY_RECONCILABLE", "CONFIRM_RECONCILE"
    elif row[0] != state["oid"]:
        status, action = "UNKNOWN_PRESERVED", "MANUAL_INSPECTION"
    else:
        status, action = "OWNED_QUARANTINE", "VERIFIED_ROLLBACK"
    proof = service.digest(
        service.canonical(
            {"journal": state, "observed": row, "cluster": cluster, "target": str(target)}
        )
    )
    return state, row, {"state": status, "action": action, "inspection_sha256": proof}


def inspect_restore(*, target, synthetic_fixtures_only=False):
    service.guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=True)
    target = service.safe_directory(target)
    try:
        with service.target_operation(target):
            return _inspect(target)[2]
    except service.RecoveryError as exc:
        if str(exc) == "target_operation_busy":
            return {"state": "BUSY", "action": "WAIT"}
        raise


def reconcile(
    *, target, expected_inspection_sha256, confirmed=False, synthetic_fixtures_only=False
):
    """Only records an already matching DB nonce/OID; never assigns ownership or drops anything."""
    service.guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=True)
    service.require(confirmed is True, "explicit_reconciliation_required")
    target = service.safe_directory(target)
    with service.target_operation(target):
        state, row, report = _inspect(target)
        service.require(
            report["inspection_sha256"] == expected_inspection_sha256, "inspection_changed"
        )
        service.require(report["state"] == "IDENTITY_RECONCILABLE", "quarantine_not_reconcilable")
        state.update(oid=row[0], state="FAILED_IDENTITY_RECONCILED")
        service.journal(target, state)
        return _inspect(target)[2]
