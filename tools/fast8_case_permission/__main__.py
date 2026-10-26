"""UTF-8 metadata in/out only; no paths, URLs, users, writes or external services."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown caller arguments, potentially private.
        self.exit(2, "INVALID_ARGUMENTS: use --help for the synthetic-only CLI contract.\n")


def _write(value: dict) -> None:
    sys.stdout.buffer.write(
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(
        description="Offline synthetic case permission receipts. Every decision is DENY; exit 0 never grants access.",
        allow_abbrev=False,
    )
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    describe = commands.add_parser(
        "describe", allow_abbrev=False, help="describe a fixed queue case"
    )
    describe.add_argument("--case-key", required=True)
    describe.add_argument(
        "--scenario-resource",
        default="synthetic::case",
        help="explicit hypothetical permission_lab context; never inferred from the row",
    )
    evaluate = commands.add_parser(
        "evaluate", allow_abbrev=False, help="revalidate a receipt and explain DENY"
    )
    evaluate.add_argument("--case-key", required=True)
    evaluate.add_argument(
        "--actor", required=True, help="hypothetical role label, never a real user"
    )
    evaluate.add_argument("--action", required=True)
    evaluate.add_argument("--target-state")
    evaluate.add_argument(
        "--descriptor-stdin",
        required=True,
        action="store_true",
        help="read at most 8192 UTF-8 bytes of descriptor JSON",
    )
    arguments = parser.parse_args(argv)

    from apps.fast8_case_permission.services import (
        MAX_DESCRIPTOR_BYTES,
        ContextError,
        describe_case,
        evaluate_case,
        parse_descriptor,
        rejected_decision,
    )
    from apps.permission_lab.sources import INVENTORY_SHA256, SOURCE_COMMIT

    try:
        if arguments.command == "describe":
            descriptor = describe_case(
                arguments.case_key, scenario_resource=arguments.scenario_resource
            )
            _write(asdict(descriptor))
            return 0
        try:
            raw = sys.stdin.buffer.read(MAX_DESCRIPTOR_BYTES + 1)
            descriptor = parse_descriptor(raw.decode("utf-8"))
        except UnicodeError as exc:
            raise ContextError("INVALID_DESCRIPTOR") from exc
        decision = evaluate_case(
            case_key=arguments.case_key,
            descriptor=descriptor,
            actor=arguments.actor,
            action=arguments.action,
            target_state=arguments.target_state,
        )
    except ContextError as exc:
        decision = rejected_decision(str(exc))

    report = asdict(decision)
    report.update(
        scope="SYNTHETIC_DIAGNOSTICS_ONLY",
        scenario_binding="EXPLICIT_HYPOTHESIS_NOT_CASE_POLICY",
        active_grants=0,
        runtime_executable=False,
        policy_source={"source_commit": SOURCE_COMMIT, "inventory_sha256": INVENTORY_SHA256},
        gates={
            "gate_b": "NOT_PASSED",
            "gates_c_d_e": "HOLD",
            "phase01": "BLOCKED",
            "scope": "SCOPE_DEVIATION_HOLD",
            "deployment": "NOT_DEPLOYED",
            "U03_U10": "OWNER_APPROVAL_PENDING",
        },
    )
    _write(report)
    return 0 if decision.context_status == "VERIFIED" and decision.valid_combination else 3


if __name__ == "__main__":
    raise SystemExit(main())
