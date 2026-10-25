"""Run the synthetic policy-gap report without Django or external input files."""

import argparse
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline synthetic policy-gap report. All decisions remain DENY. "
            "A successful exit means reporting completed; it never grants permission."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        required=True,
        help="acknowledge that this is a synthetic development report only",
    )
    parser.add_argument("--actor", help="synthetic candidate actor")
    parser.add_argument("--action", help="synthetic candidate action")
    parser.add_argument("--resource", help="synthetic candidate resource")
    parser.add_argument("--target-state", help="optional synthetic candidate target state")
    arguments = parser.parse_args(argv)
    candidate_fields = (arguments.actor, arguments.action, arguments.resource)
    supplied = tuple(field is not None for field in candidate_fields)
    if any(supplied) and not all(supplied):
        parser.error("--actor, --action and --resource must be supplied together")
    if arguments.target_state is not None and not all(supplied):
        parser.error("--target-state requires --actor, --action and --resource")

    from apps.policy_gap_engine.services import CandidateRequest, build_report, canonical_json

    requests = None
    if all(supplied):
        requests = (CandidateRequest(*candidate_fields, target_state=arguments.target_state),)
    report = build_report(requests)
    sys.stdout.buffer.write(canonical_json(report).encode("utf-8"))
    if (
        report["status"] == "EVIDENCE_UNAVAILABLE"
        or report["adversarial_checks"]["status"] == "FAIL"
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
