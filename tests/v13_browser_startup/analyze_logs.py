"""Compare the two D6 FAST6 job logs without guessing the timeout's cause.

Only bounded allowlisted facts are emitted. Inputs are untrusted decoded logs;
no log instruction, URL, shell command or raw browser stderr is executed/exported.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

CATALOG = "fixed synthetic test double; no database"
COMMAND = "python -B manage.py test tests.fast6_journey.test_browser"
MAX_LOG = 2 * 1024 * 1024
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z ")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class EvidenceError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise EvidenceError(code)


def normalized(raw):
    require(type(raw) is bytes and len(raw) <= MAX_LOG, "LOG_SIZE_INVALID")
    try:
        return raw.decode("utf-8-sig").replace("\r\n", "\n").rstrip("\n") + "\n"
    except UnicodeError as exc:
        raise EvidenceError("LOG_ENCODING_INVALID") from exc


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "REPORT_DUPLICATE_KEY")
        result[key] = value
    return result


def parse(raw, *, expected_sha, outcome):
    require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "SHA_INVALID")
    require(outcome in {"failure", "success"}, "OUTCOME_INVALID")
    text = normalized(raw)
    lines = [ANSI.sub("", STAMP.sub("", line)) for line in text.splitlines()]
    checkouts = [
        lines[i + 1]
        for i, line in enumerate(lines[:-1])
        if line == "[command]/usr/bin/git log -1 --format=%H"
    ]
    require(checkouts == [expected_sha], "CHECKOUT_SHA_MISMATCH")
    starts = [i for i, line in enumerate(lines) if line.startswith("##[group]Run " + COMMAND)]
    require(len(starts) == 1, "FAST6_STEP_AMBIGUOUS")
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("##[group]")), len(lines)
    )
    reports = []
    for line in lines[start:end]:
        offset = line.find('{"result":')
        if offset < 0:
            continue
        try:
            value = json.loads(line[offset:], object_pairs_hook=unique_keys)
        except (ValueError, RecursionError) as exc:
            raise EvidenceError("REPORT_JSON_INVALID") from exc
        require(type(value) is dict, "REPORT_SHAPE_INVALID")
        if value.get("catalog") == CATALOG:
            reports.append(value)
    require(len(reports) == 1, "FAST6_REPORT_AMBIGUOUS")
    report = reports[0]
    startup = report.get("startup", {})
    require(type(startup) is dict, "STARTUP_SHAPE_INVALID")
    require(startup.get("timeout_ms") == 30000, "STARTUP_LIMIT_CHANGED")
    elapsed = startup.get("elapsed_ms")
    require(type(elapsed) is int and elapsed >= 0, "ELAPSED_INVALID")
    require(report.get("cleanup") == {"result": "PASS", "errors": []}, "CLEANUP_NOT_PROVEN")
    diagnostics = report.get("diagnostics")
    require(diagnostics == {"stderr_present": True, "stderr_hints": []}, "DIAGNOSTICS_CHANGED")
    if outcome == "failure":
        require(report.get("result") == "NOT_RUN", "FAILED_JOURNEY_NOT_NOT_RUN")
        require(
            report.get("failure")
            == {"code": "BROWSER_STARTUP_TIMEOUT", "stage": "websocket", "cause_code": None}
            and startup.get("stage") == "websocket"
            and elapsed >= 30000,
            "FAILURE_CONTRACT_CHANGED",
        )
        require(
            any("AssertionError: 2 != 0" in line for line in lines[start:end]), "EXIT_TWO_UNPROVEN"
        )
    else:
        require(
            report.get("result") == "PASS"
            and startup.get("stage") == "ready"
            and elapsed < 30000
            and "failure" not in report,
            "SUCCESS_CONTRACT_CHANGED",
        )

    def unique(pattern):
        values = [m.group(1) for line in lines if (m := re.fullmatch(pattern, line))]
        require(len(values) == 1, "ENVIRONMENT_FIELD_AMBIGUOUS")
        return values[0]

    return {
        "decoded_log_normalized_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "sha": checkouts[0],
        "result": report["result"],
        "startup": {"stage": startup["stage"], "elapsed_ms": elapsed, "timeout_ms": 30000},
        "cleanup": "PASS",
        "diagnostics": diagnostics,
        "runner_image": unique(r"Image: (ubuntu-[0-9.]+)"),
        "runner_image_version": unique(r"Version: ([0-9]{8}\.[0-9]+\.[0-9]+)"),
        "region": unique(r"Region: ([a-z0-9]+)"),
        "chrome": unique(r"Google Chrome ([0-9.]+) *"),
        "node": unique(r"node: (v[0-9.]+)"),
        "python": unique(r"Successfully set up CPython \(([0-9.]+)\)"),
    }


def compare(failure, success, *, expected_sha):
    first = parse(failure, expected_sha=expected_sha, outcome="failure")
    second = parse(success, expected_sha=expected_sha, outcome="success")
    return {
        "schema": "fatwa.v13.d6-log-comparison.v1",
        "failure": first,
        "success": second,
        "matching_observed_environment": {
            key: first[key] == second[key]
            for key in ("sha", "runner_image", "runner_image_version", "chrome", "node", "python")
        },
        "same_region": first["region"] == second["region"],
        "root_cause": "ROOT_CAUSE_UNKNOWN",
        "historical_failure_retained": True,
        "startup_duration_is_total_not_websocket_duration": True,
        "real_source_acceptance": "NOT_RUN",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failure", type=Path, required=True)
    parser.add_argument("--success", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()

    def read(path):
        with path.open("rb") as stream:
            return stream.read(MAX_LOG + 1)

    try:
        result = compare(read(args.failure), read(args.success), expected_sha=args.expected_sha)
    except (OSError, EvidenceError) as exc:
        parser.exit(2, str(exc) if isinstance(exc, EvidenceError) else "LOG_READ_FAILED")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
