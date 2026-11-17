"""Run one command inside a fresh local PostgreSQL 17/18 synthetic cluster.

The server and command share one process lifetime, which also supports executors
that isolate loopback networking between calls. No installed server is contacted.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--major", required=True, choices=("17", "18"))
    parser.add_argument("--settings", default="config.settings.casework_test")
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a test/check command is required after --")
    binaries = args.pg_bin.resolve(strict=True)
    env = os.environ.copy()
    version = subprocess.check_output([str(binaries / "postgres"), "--version"], text=True)
    if re.search(r"\(PostgreSQL\) " + args.major + r"\.", version) is None:
        parser.error("the supplied PostgreSQL binary has a different major version")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    for key in ("DATABASE_URL", "PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGPASSFILE", "PGOPTIONS"):
        env.pop(key, None)
    env.update(
        FATWA_PRODUCTION="0", FATWA_WAVE7_SYNTHETIC_WRITES="1",
        DJANGO_SETTINGS_MODULE=args.settings, PGHOST="127.0.0.1", PGPORT=str(port),
        PGUSER="wave7_synthetic", PGPASSWORD="", PGDATABASE="wave7_synthetic_v6local",
        PGTESTDATABASE="test_wave7_synthetic_v6local", PG_EXPECTED_MAJOR=args.major,
        PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""),
    )
    scratch = Path.cwd() / ".local" / "postgres"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"v6-pg{args.major}-", dir=scratch) as directory:
        root = Path(directory)
        data, log = root / "data", root / "server.log"
        started = False
        try:
            subprocess.run([
                str(binaries / "initdb"), "-D", str(data), "-U", "wave7_synthetic",
                "--auth-local=trust", "--auth-host=trust", "--locale=C.UTF-8", "--encoding=UTF8",
            ], env=env, check=True, stdout=subprocess.DEVNULL)
            subprocess.run([
                str(binaries / "pg_ctl"), "-D", str(data), "-l", str(log),
                "-o", f"-h 127.0.0.1 -p {port} -c unix_socket_directories=''", "-w", "start",
            ], env=env, check=True, stdout=subprocess.DEVNULL)
            started = True
            subprocess.run([
                str(binaries / "createdb"), "-h", "127.0.0.1", "-p", str(port),
                "-U", "wave7_synthetic", env["PGDATABASE"],
            ], env=env, check=True)
            print(f"SYNTHETIC_POSTGRES={version.strip()}; fresh owned cluster", flush=True)
            if not args.no_bootstrap:
                subprocess.run([
                    sys.executable, "-c",
                    "import django; django.setup(); "
                    "from apps.intake_workflow.guards import initialize_synthetic_database; "
                    "initialize_synthetic_database(synthetic_fixtures_only=True); "
                    "from django.core.management import call_command; "
                    "call_command('migrate', interactive=False, verbosity=0)",
                ], env=env, check=True)
            return subprocess.run(command, env=env).returncode
        finally:
            if started:
                subprocess.run([
                    str(binaries / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop",
                ], env=env, check=True, stdout=subprocess.DEVNULL)
            elif log.exists():
                print(log.read_text(encoding="utf-8"), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
