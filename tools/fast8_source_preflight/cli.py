"""Read exactly one explicit receipt file; no archive or source path arguments."""

import json
import sys

from apps.fast8_source_preflight.service import BASE_SHA, Verdict, verify_receipt
from apps.source_readiness.service import MAX_MANIFEST_BYTES
from tools.source_readiness.cli import ReadError, SafeArgumentParser, read_local

EXIT_CODES = {"RECEIPT_VERIFIED": 0, "FAIL": 1, "BLOCKED": 2, "NOT_RUN": 3}


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -m tools.fast8_source_preflight",
        allow_abbrev=False,
        description="Verify a pinned local synthetic receipt; never open source archives.",
    )
    parser.add_argument("--receipt")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--as-of", help="Explicit UTC YYYY-MM-DDTHH:MM:SSZ")
    parser.add_argument("--expected-revision", default=BASE_SHA)
    try:
        args = parser.parse_args(argv)
        if args.receipt and (args.expected_sha256 is None or args.as_of is None):
            report = Verdict("BLOCKED", ("external_pin_and_as_of_required",))
        else:
            receipt = (
                read_local(args.receipt, "RECEIPT", MAX_MANIFEST_BYTES) if args.receipt else None
            )
            report = verify_receipt(
                receipt,
                expected_sha256=args.expected_sha256,
                as_of=args.as_of,
                expected_revision=args.expected_revision,
            )
    except ReadError as error:
        report = Verdict("BLOCKED", (str(error),))
    sys.stdout.write(json.dumps(report.as_dict(), ensure_ascii=True, sort_keys=True) + "\n")
    return EXIT_CODES[report.status]
