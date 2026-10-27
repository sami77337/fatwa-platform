"""Bounded UTF-8 stdin/stdout only; no paths, credentials, URLs or data writes."""

import argparse
import json
import os
import sys


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "INVALID_ARGUMENTS: use --help for synthetic diagnostics.\n")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    parser = Parser(
        description="Synthetic case/policy evidence only. Exit 0 is still DENY.", allow_abbrev=False
    )
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("command", choices=("select", "evaluate"))
    for name in ("case-key", "actor", "action", "resource"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--target-state")
    parser.add_argument("--receipt-stdin", action="store_true")
    flags = [value.split("=", 1)[0] for value in args if value.startswith("--")]
    if len(flags) != len(set(flags)):
        parser.error("duplicate flags")
    parsed = parser.parse_args(args)
    if parsed.receipt_stdin != (parsed.command == "evaluate"):
        parser.error("receipt mode")
    if os.environ.get("FATWA_PRODUCTION", "0") != "0":
        parser.error("production disabled")
    from apps.fast9_case_policy_join import services

    try:
        text = None
        if parsed.receipt_stdin:
            text = sys.stdin.buffer.read(services.MAX_RECEIPT_BYTES + 1).decode("utf-8")
        result = services.inspect_request(
            case_key=parsed.case_key,
            actor=parsed.actor,
            action=parsed.action,
            resource=parsed.resource,
            target_state=parsed.target_state,
            receipt_text=text,
        )
    except UnicodeError:
        result = services.rejected("INVALID_RECEIPT")
    sys.stdout.buffer.write(
        (
            json.dumps(services.report(result), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
    )
    return 0 if result.synthetic_context == "VERIFIED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
