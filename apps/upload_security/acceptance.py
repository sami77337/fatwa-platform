"""Run actual configured ClamAV against synthetic benign/EICAR inputs only.

This CLI reads an explicitly supplied installed engine and official CVD snapshot;
it never downloads signatures, starts a daemon, changes product settings, writes
domain rows, or treats a mock/marker implementation as real scanner evidence.
"""

import argparse
import json
import math
import re
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import file_digest, sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .clamav import (
    DATABASES,
    MAX_DATABASE_BYTES,
    PROFILE,
    ClamAVConfig,
    ClamAVScanner,
    DatabasePin,
    _cvd_header,
    execute_process,
)
from .contract import ScanInput, ScannerUnavailable
from .execution import invoke

BENIGN = b"SYNTHETIC benign Fatwa Platform upload acceptance.\r\nNo source or user data.\n"
# Standard harmless 68-byte AV installation test, distributed by EICAR:
# https://www.eicar.org/download-anti-malware-testfile/
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def _hash(path, maximum):
    if not path.is_file() or not 1 <= path.stat().st_size <= maximum:
        raise ScannerUnavailable
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


class ObservedClamAV(ClamAVScanner):
    """Only collect bounded diagnostics from the unchanged real process adapter."""

    def __init__(self, config):
        self.reports = []
        super().__init__(config)

    def _execute(self, command, root, deadline):
        code, raw = super()._execute(command, root, deadline)
        self.reports.append(
            {
                "return_code": code,
                "report_sha256": sha256(raw).hexdigest(),
                "report": raw.decode("utf-8", errors="replace"),
            }
        )
        return code, raw


def evaluate(
    *,
    executable,
    database_directory,
    max_daily_age_days,
    memory_bytes,
    timeout_seconds,
    signature_source,
):
    evidence = {
        "schema": "fatwa.upload-security.clamav-acceptance.v1",
        "observed_at": datetime.now(UTC).isoformat(),
        "status": "UNAVAILABLE",
        "real_engine_verified": False,
        "signature_source_reported_by_operator": signature_source,
        "signature_authentication": "ClamAV official CVD verification; no unsigned override",
        "production_changed": False,
        "domain_rows_written": False,
        "samples_are_synthetic": True,
        "profile": list(PROFILE),
        "databases": [],
        "samples": [],
        "reports": [],
        "failure_stage": "configuration",
    }
    scanner = None
    try:
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0.01 <= timeout_seconds <= 30
            or type(signature_source) is not str
            or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._/-]*)?", signature_source)
        ):
            raise ScannerUnavailable
        evidence["failure_stage"] = "engine_or_database_path"
        executable = Path(executable).resolve(strict=True)
        directory = Path(database_directory).resolve(strict=True)
        executable_sha = _hash(executable, 64 * 1024 * 1024)
        evidence["failure_stage"] = "engine_version"
        with TemporaryDirectory(prefix="fatwa-clamav-version-") as temporary:
            code, version_raw = execute_process(
                [str(executable), "--version"], Path(temporary), monotonic() + 5, memory_bytes
            )
        version = re.fullmatch(
            rb"ClamAV ([A-Za-z0-9._:-]{1,128})(?:/[^\r\n]{1,256})?\r?\n?", version_raw
        )
        if code != 0 or version is None:
            raise ScannerUnavailable
        engine_version = version[1].decode("ascii")
        if "synthetic" in engine_version.lower():
            raise ScannerUnavailable
        evidence["version_observation"] = version_raw.decode("ascii").strip()
        evidence["executable_sha256"] = executable_sha
        evidence["failure_stage"] = "database_snapshot"
        pins = []
        for name in sorted(DATABASES):
            path = directory / name
            digest = _hash(path, MAX_DATABASE_BYTES)
            with path.open("rb") as source:
                version_number, signatures, created = _cvd_header(source.read(512))
            pins.append(DatabasePin(name, digest, path.stat().st_size))
            evidence["databases"].append(
                {
                    **asdict(pins[-1]),
                    "version": version_number,
                    "declared_signatures": signatures,
                    "created_at": datetime.fromtimestamp(created, UTC).isoformat(),
                }
            )
        scanner = ObservedClamAV(
            ClamAVConfig(
                "local-clamav-acceptance",
                str(executable),
                executable_sha,
                engine_version,
                str(directory),
                tuple(pins),
                max_daily_age_days,
                memory_bytes,
            )
        )
        evidence["failure_stage"] = "current_scanner_coverage"
        evidence["scanner"] = asdict(scanner.spec)
        evidence["daily_age_limit_days"] = max_daily_age_days
        evidence["timeout_seconds_per_sample"] = timeout_seconds
        for name, raw, expected in (
            ("BENIGN_SYNTHETIC", BENIGN, "CLEAN"),
            ("EICAR_STANDARD_68_BYTES", EICAR, "BLOCKED"),
        ):
            evidence["failure_stage"] = name
            request = ScanInput(
                raw, sha256(raw).hexdigest(), len(raw), monotonic() + timeout_seconds
            )
            state, verdict = invoke(scanner, request, timeout_seconds)
            if state != "RETURNED":
                evidence["samples"].append(
                    {"name": name, "sha256": request.sha256, "size": len(raw), "state": state}
                )
                raise ScannerUnavailable
            evidence["samples"].append({"name": name, "expected": expected, **asdict(verdict)})
            if (
                verdict.status in {"UNAVAILABLE", "INCOMPLETE"}
                or not verdict.complete
                or verdict.scanned_files != 1
                or verdict.loaded_signatures < 1
            ):
                raise ScannerUnavailable
            if verdict.status != expected or verdict.spec != scanner.spec:
                evidence["status"] = "FAILED"
                return evidence
        evidence["status"] = "PASSED"
        evidence["real_engine_verified"] = True
        evidence["failure_stage"] = None
    except (OSError, ValueError, TypeError, TimeoutError, ScannerUnavailable):
        evidence["status"] = "UNAVAILABLE"
    finally:
        if scanner is not None:
            evidence["reports"] = scanner.reports
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--database-directory", required=True)
    parser.add_argument("--signature-source", required=True)
    parser.add_argument("--max-daily-age-days", required=True, type=int)
    parser.add_argument("--memory-bytes", required=True, type=int)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    values = vars(args).copy()
    output = values.pop("output")
    result = evaluate(**values)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {"status": result["status"], "real_engine_verified": result["real_engine_verified"]},
            sort_keys=True,
        )
    )
    return {"PASSED": 0, "FAILED": 1, "UNAVAILABLE": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
