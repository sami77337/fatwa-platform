"""Offline, bounded B6 evidence comparison; never infer why Chrome timed out."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from tests.v13_browser_startup.analyze_logs import (
    ANSI,
    STAMP,
    EvidenceError,
    normalized,
    require,
    unique_keys,
)

COMMAND = "python tests/acceptance/wave6/run.py --browser --review-batches"


def parse(raw, *, expected_sha, outcome):
    require(
        type(expected_sha) is str and re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None,
        "SHA_INVALID",
    )
    require(outcome in {"failure", "success"}, "OUTCOME_INVALID")
    text = normalized(raw)
    lines = [ANSI.sub("", STAMP.sub("", line)) for line in text.splitlines()]
    checkouts = [
        lines[i + 1]
        for i, line in enumerate(lines[:-1])
        if line == "[command]/usr/bin/git log -1 --format=%H"
    ]
    require(checkouts == [expected_sha], "CHECKOUT_SHA_MISMATCH")
    commands = [i for i, line in enumerate(lines) if line.startswith(COMMAND + " ")]
    require(len(commands) == 1, "B6_STEP_AMBIGUOUS")
    start = commands[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("##[group]")),
        len(lines),
    )
    reports, summaries = [], []
    for line in lines[start:end]:
        marker = "E6_BROWSER_EVIDENCE "
        if line.startswith(marker):
            target, value = reports, line[len(marker) :]
        elif (offset := line.find('{"result":')) >= 0:
            target, value = summaries, line[offset:]
        else:
            continue
        try:
            decoded = json.loads(value, object_pairs_hook=unique_keys)
        except (ValueError, RecursionError) as exc:
            raise EvidenceError("REPORT_JSON_INVALID") from exc
        require(type(decoded) is dict, "REPORT_SHAPE_INVALID")
        target.append(decoded)
    require(len(reports) == len(summaries) == 1, "B6_REPORT_AMBIGUOUS")
    report, summary = reports[0], summaries[0]
    require(report.get("sha") == expected_sha, "REPORT_SHA_MISMATCH")
    counts = {"PASS": 0, "FAIL": 0, "NOT_RUN": 10, "SKIP": 0}
    result, status = "BLOCKED", "NOT_RUN"
    if outcome == "success":
        counts.update(PASS=10, NOT_RUN=0)
        result, status = "PASS", "PASS"
    for item in [report, summary]:
        actual = item.get("counts")
        require(
            type(actual) is dict
            and all(type(n) is int for n in actual.values())
            and actual == counts
            and item.get("result") == result,
            "RESULT_COUNTS_MISMATCH",
        )
    cases = report.get("tests")
    require(
        type(cases) is list
        and len(cases) == 10
        and all(type(case) is dict and case.get("result") == status for case in cases),
        "CASE_RESULTS_MISMATCH",
    )
    if outcome == "failure":
        require(summary.get("blocker") == "Timed out: DevTools launch", "BLOCKER_MISMATCH")
        require("browser" not in report, "UNEXPECTED_BROWSER_SESSION")
        require(
            any(
                "AssertionError: 2 != 0 : E6 browser gate failed/blocked;" in line
                for line in lines[start:end]
            ),
            "EXIT_TWO_UNPROVEN",
        )
    else:
        require("blocker" not in summary, "SUCCESS_HAS_BLOCKER")
        require(type(report.get("browser")) is dict, "BROWSER_SESSION_MISSING")
        product = report["browser"].get("product")
        require(
            type(product) is str and re.fullmatch(r"Chrome/[0-9.]{1,30}", product),
            "BROWSER_VERSION_INVALID",
        )
    environment = report.get("environment")
    require(type(environment) is dict, "ENVIRONMENT_INVALID")
    chrome, node = environment.get("browser", ""), environment.get("node", "")
    require(
        type(chrome) is str and re.fullmatch(r"Google Chrome [0-9.]{1,30}", chrome),
        "CHROME_INVALID",
    )
    require(type(node) is str and re.fullmatch(r"v[0-9.]{1,30}", node), "NODE_INVALID")
    return {
        "decoded_log_normalized_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "checkout_sha": expected_sha,
        "result": result,
        "counts": counts,
        "observed_boundary": "PORT_FILE_POLL" if outcome == "failure" else "JOURNEY_COMPLETED",
        "browser_version_probe": chrome,
        "browser_session_version": report["browser"]["product"] if outcome == "success" else None,
        "node": node,
        "startup_elapsed_ms": None,
        "root_cause": "ROOT_CAUSE_UNKNOWN",
    }


def compare(failure, success, *, expected_sha):
    return {
        "schema": "fatwa.v14.b6-log-comparison.v1",
        "failure": parse(failure, expected_sha=expected_sha, outcome="failure"),
        "success": parse(success, expected_sha=expected_sha, outcome="success"),
        "root_cause": "ROOT_CAUSE_UNKNOWN",
        "later_success_explains_failure": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("failure", type=Path)
    parser.add_argument("success", type=Path)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    try:
        result = compare(
            args.failure.read_bytes(), args.success.read_bytes(), expected_sha=args.sha
        )
    except (EvidenceError, OSError):
        # Never echo attacker-controlled log fragments or paths into CI.
        parser.exit(2, "B6_EVIDENCE_INVALID\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
