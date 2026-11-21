"""Explicit local ClamAV adapter; absent or unverifiable coverage is unavailable.

The operator supplies the actual executable/version and immutable official CVD
snapshot hashes. Construction verifies that snapshot outside any request/DB unit.
Updating it requires a new adapter/configuration, and invalidates old receipts.
No daemon, downloader, network call, bundled signatures or fallback engine exists.
"""

import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, time

from .contract import (
    MAX_BYTES,
    FileScanner,
    ScanInput,
    ScannerSpec,
    ScannerUnavailable,
    ScanVerdict,
)

HASH = re.compile(r"[a-f0-9]{64}\Z")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
DATABASES = frozenset({"main.cvd", "daily.cvd", "bytecode.cvd"})
MAX_DATABASE_BYTES = 512 * 1024 * 1024
MAX_REPORT_BYTES = 32768
PROFILE = (
    "--stdout",
    "--official-db-only=yes",
    "--bytecode=yes",
    "--bytecode-unsigned=no",
    "--heuristic-alerts=yes",
    "--alert-broken=yes",
    "--alert-encrypted=yes",
    "--alert-exceeds-max=yes",
    "--scan-archive=yes",
    "--scan-pdf=yes",
    "--scan-image=yes",
    "--scan-image-fuzzy-hash=yes",
    "--scan-pe=yes",
    "--scan-elf=yes",
    "--scan-ole2=yes",
    "--scan-html=yes",
    "--scan-swf=yes",
    "--disable-cache",
    # Engine time limits may skip content; the enclosing process has a hard wall limit.
    "--max-scantime=0",
    f"--max-filesize={MAX_BYTES}",
    f"--max-scansize={MAX_BYTES * 4}",
    f"--pcre-max-filesize={MAX_BYTES * 4}",
    "--max-files=64",
    "--max-recursion=16",
    "--follow-dir-symlinks=0",
    "--follow-file-symlinks=0",
)


@dataclass(frozen=True, slots=True)
class DatabasePin:
    name: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ClamAVConfig:
    key: str
    executable: str
    executable_sha256: str
    engine_version: str
    database_directory: str
    databases: tuple[DatabasePin, ...]
    max_daily_age_days: int
    memory_bytes: int


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _path(value):
    if type(value) is not str or not value or "\0" in value:
        raise ScannerUnavailable
    path = Path(value)
    if not path.is_absolute() or str(path.resolve(strict=True)) != value:
        raise ScannerUnavailable
    return path


def _stamp(path, maximum):
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or not 1 <= info.st_size <= maximum
        or info.st_mode & 0o022
        or info.st_uid not in {0, os.getuid()}
    ):
        raise ScannerUnavailable
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
    )


def _read_pin(path, expected, size, maximum):
    stamp = _stamp(path, maximum)
    if size is not None and stamp[2] != size:
        raise ScannerUnavailable
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as source:
        first = source.read(512)
        digest = sha256(first)
        total = len(first)
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise ScannerUnavailable
            digest.update(chunk)
    if digest.hexdigest() != expected or _stamp(path, maximum) != stamp or total != stamp[2]:
        raise ScannerUnavailable
    return stamp, first


def _cvd_header(header):
    try:
        parts = header.decode("ascii").rstrip(" \r\n\0").split(":")
        if (
            len(header) != 512
            or len(parts) != 9
            or parts[0] != "ClamAV-VDB"
            or any(not re.fullmatch(r"[0-9]{1,10}", parts[index]) for index in (2, 3, 4, 8))
            or int(parts[2]) < 1
            or int(parts[3]) < 1
            or int(parts[8]) < 1
        ):
            raise ValueError
        return int(parts[2]), int(parts[3]), int(parts[8])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise ScannerUnavailable from exc


class ClamAVScanner(FileScanner):
    def __init__(self, config):
        self.config = config
        self._snapshot = None
        try:
            self._validate_config()
            self._snapshot = self._fingerprint()
        except (OSError, ValueError, TypeError, ScannerUnavailable):
            # Explicitly unavailable until an operator supplies a valid new snapshot.
            pass

    def _validate_config(self):
        config = self.config
        if (
            type(config) is not ClamAVConfig
            or any(
                type(value) is not str or not REF.fullmatch(value)
                for value in (config.key, config.engine_version)
            )
            or type(config.executable_sha256) is not str
            or not HASH.fullmatch(config.executable_sha256)
            or type(config.databases) is not tuple
            or len(config.databases) != 3
            or any(type(pin) is not DatabasePin for pin in config.databases)
            or {pin.name for pin in config.databases} != DATABASES
            or any(
                type(pin.sha256) is not str
                or not HASH.fullmatch(pin.sha256)
                or type(pin.size) is not int
                or not 512 <= pin.size <= MAX_DATABASE_BYTES
                for pin in config.databases
            )
            or type(config.max_daily_age_days) is not int
            or not 1 <= config.max_daily_age_days <= 30
            or type(config.memory_bytes) is not int
            or not 256 * 1024 * 1024 <= config.memory_bytes <= 4 * 1024 * 1024 * 1024
        ):
            raise ScannerUnavailable

    def _directory(self):
        directory = _path(self.config.database_directory)
        info = directory.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_mode & 0o022
            or info.st_uid not in {0, os.getuid()}
        ):
            raise ScannerUnavailable
        if {entry.name for entry in directory.iterdir()} != DATABASES:
            raise ScannerUnavailable
        return directory

    def _fingerprint(self):
        executable = _path(self.config.executable)
        if not os.access(executable, os.X_OK):
            raise ScannerUnavailable
        engine, _ = _read_pin(executable, self.config.executable_sha256, None, 64 * 1024 * 1024)
        directory = self._directory()
        databases = []
        for pin in sorted(self.config.databases, key=lambda item: item.name):
            stamp, header = _read_pin(
                directory / pin.name, pin.sha256, pin.size, MAX_DATABASE_BYTES
            )
            databases.append((pin.name, stamp, _cvd_header(header)))
        return engine, tuple(databases)

    @property
    def spec(self):
        try:
            self._validate_config()
            if self._snapshot is None:
                raise ScannerUnavailable
            if _stamp(_path(self.config.executable), 64 * 1024 * 1024) != self._snapshot[0]:
                raise ScannerUnavailable
            directory = self._directory()
            daily_created = None
            versions = []
            for name, stamp, header in self._snapshot[1]:
                if _stamp(directory / name, MAX_DATABASE_BYTES) != stamp:
                    raise ScannerUnavailable
                versions.append(f"{name.removesuffix('.cvd')}.{header[0]}")
                if name == "daily.cvd":
                    daily_created = header[2]
            if (
                daily_created is None
                or not -300 <= time() - daily_created < self.config.max_daily_age_days * 86400
            ):
                raise ScannerUnavailable
            return ScannerSpec(
                self.config.key,
                self.config.engine_version,
                "cvd." + ".".join(versions),
                _digest(
                    [
                        asdict(pin)
                        for pin in sorted(self.config.databases, key=lambda item: item.name)
                    ]
                ),
                _digest(
                    {
                        "config": asdict(self.config),
                        "profile": PROFILE,
                        "contract": "clamav-local-1",
                    }
                ),
                "CONFIGURED",
            )
        except (OSError, ValueError, TypeError) as exc:
            raise ScannerUnavailable from exc

    def _execute(self, command, root, deadline):
        return execute_process(command, root, deadline, self.config.memory_bytes)

    def scan(self, request):
        selected = self.spec
        if (
            type(request) is not ScanInput
            or type(request.raw) is not bytes
            or type(request.size) is not int
            or not 1 <= request.size <= MAX_BYTES
            or len(request.raw) != request.size
            or sha256(request.raw).hexdigest() != request.sha256
        ):
            raise ScannerUnavailable

        def verdict(status, complete=False, scanned=0, loaded=0):
            return ScanVerdict(
                status, request.sha256, request.size, selected, complete, scanned, loaded
            )

        try:
            if self._fingerprint() != self._snapshot or monotonic() >= request.deadline_monotonic:
                return verdict("UNAVAILABLE")
            with TemporaryDirectory(prefix="fatwa-scan-") as temporary:
                root = Path(temporary)
                original = root / "upload.original"
                original.write_bytes(request.raw)
                original.chmod(0o400)
                command = [
                    self.config.executable,
                    *PROFILE,
                    f"--database={self.config.database_directory}",
                    f"--fail-if-cvd-older-than={self.config.max_daily_age_days}",
                    str(original),
                ]
                code, output = self._execute(command, root, request.deadline_monotonic)
                if (
                    self.spec != selected
                    or self._fingerprint() != self._snapshot
                    or monotonic() >= request.deadline_monotonic
                    or original.read_bytes() != request.raw
                ):
                    return verdict("UNAVAILABLE")
                if code == 1:
                    loaded = complete_report(
                        output, str(original), selected.engine_version, infected=True
                    )
                    return verdict("BLOCKED", loaded is not None, 1 if loaded else 0, loaded or 0)
                if code != 0:
                    return verdict("UNAVAILABLE")
                loaded = complete_report(output, str(original), selected.engine_version)
                if loaded is None:
                    return verdict("INCOMPLETE")
                return verdict("CLEAN", True, 1, loaded)
        except (OSError, ValueError, TimeoutError, ScannerUnavailable):
            return verdict("UNAVAILABLE")


def execute_process(command, root, deadline, memory_bytes):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError
    report_path = root / "scan-report"
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "TMPDIR": str(root)}
    request = {
        "command": command,
        "memory_bytes": memory_bytes,
        "cpu_seconds": max(1, math.ceil(remaining)),
    }
    with report_path.open("xb") as output:
        os.chmod(report_path, 0o600)
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("clamav_worker.py")),
                json.dumps(request),
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            cwd=root,
            env=environment,
            start_new_session=True,
            close_fds=True,
        )
        try:
            code = process.wait(timeout=remaining)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # The controller retains its single slot until this child exits.
            process.wait()
            raise TimeoutError from None
    with report_path.open("rb") as report:
        raw = report.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ScannerUnavailable
    return code, raw


def complete_report(raw, path, engine_version, *, infected=False):
    """Allow only the complete known one-file summary; reject all extra diagnostics."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_REPORT_BYTES:
        return None
    try:
        lines = [line for line in raw.decode("ascii").splitlines() if line]
    except UnicodeError:
        return None
    first = re.escape(path) + (r": [A-Za-z0-9_.-]{1,120} FOUND" if infected else ": OK")
    if (
        len(lines) < 2
        or re.fullmatch(first, lines[0]) is None
        or lines[1] != "----------- SCAN SUMMARY -----------"
    ):
        return None
    # Older supported releases use decimal MB; current upstream uses B/KiB/MiB/GiB.
    amount = r"[0-9]+(?:\.[0-9]+)? (?:B|KiB|MiB|GiB|MB)"
    patterns = {
        "Known viruses": r"[1-9][0-9]{0,8}",
        "Engine version": re.escape(engine_version),
        "Scanned directories": "0",
        "Scanned files": "1",
        "Infected files": "1" if infected else "0",
        "Data scanned": amount,
        "Data read": amount + r" \(ratio [0-9]+\.[0-9]+:1\)",
        "Time": r"[0-9]+\.[0-9]+ sec \([0-9]+ m [0-9]+ s\)",
        "Start Date": r"[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}",
        "End Date": r"[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}",
    }
    seen = {}
    for line in lines[2:]:
        key, separator, value = line.partition(": ")
        if (
            not separator
            or key in seen
            or key not in patterns
            or re.fullmatch(patterns[key], value) is None
        ):
            return None
        seen[key] = value
    if set(seen) != set(patterns):
        return None
    return int(seen["Known viruses"])
