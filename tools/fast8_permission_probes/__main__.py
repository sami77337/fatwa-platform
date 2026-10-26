"""Fixed synthetic adversarial checks; no caller records, policy files or writes."""

import argparse
import json
import sys

from .runner import load_scenarios, run_suite


def exit_code(report: dict) -> int:
    return {"PASS": 0, "FAIL": 1, "NOT_RUN": 3}[report["status"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic offline permission QA. PASS never grants permission.",
        allow_abbrev=False,
    )
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list the fixed regression scenarios")
    group.add_argument("--scenario", help="run one exact bundled scenario ID")
    args = parser.parse_args(argv)
    try:
        report = (
            load_scenarios()[0]
            if args.list
            else run_suite((args.scenario,) if args.scenario is not None else None)
        )
    except (ValueError, KeyError, OSError):
        # Do not echo arbitrary caller text or filesystem details.
        parser.error("invalid or unavailable fixed scenario manifest/selection")
    sys.stdout.buffer.write(
        (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return 0 if args.list else exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
