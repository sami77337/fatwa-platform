"""B6 separated QA; no live database credentials, imports, or persistent volumes."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
# Directory labels avoid Python 3.13 unittest discovery on the namespace-only
# tests package. Include the wave2 API, SSR and read-only command regressions.
APP_TESTS = [
    "tests/reference", "tests/public_site", "tests/security",
    "tests/integration/api", "tests/integration/ui",
    "tests.integration.source.test_read_only_commands", "tests.integration.test_site",
    "tests.reference_links_db.test_catalog_adapter",
]


class DockerUnavailable(RuntimeError):
    """No application or migration checks have executed."""


def environment():
    return {k: v for k, v in os.environ.items() if not re.search(
        r"^(PG|DJANGO_|FATWA_|DATABASE_URL$|DOCKER_|PYTHONPATH$|PYTHONHOME$|NODE_OPTIONS$)|"
        r"PASSWORD|SECRET|TOKEN|API_KEY", k, re.I)} | {
        "PYTHONDONTWRITEBYTECODE": "1", "FATWA_PRODUCTION": "0",
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "PGHOST": "127.0.0.1", "PGPORT": "1", "PGDATABASE": "b6_unreachable",
    }


def run(args, *, env=None, timeout=120, capture=False):
    return subprocess.run(args, cwd=ROOT, env=env or environment(), shell=False,
                          timeout=timeout, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def committed():
    sha = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    dirty = bool(run(["git", "status", "--porcelain", "--untracked-files=normal"], capture=True).stdout)
    if os.environ.get("CI") and dirty:
        raise RuntimeError("CI requires a clean checkout of committed code")
    return {"sha": sha, "working_tree": "DIRTY" if dirty else "CLEAN"}


def system():
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Python 3.13 required")
    # This is Django's actual system checker; port 1 prevents a live DB fallback.
    run([sys.executable, "manage.py", "check", "--settings=config.settings.test"])


def docker_transport(endpoint):
    if not re.fullmatch(r"npipe:////\./pipe/[A-Za-z0-9_.-]+|unix:///[A-Za-z0-9_./ -]+", endpoint):
        raise RuntimeError("Only a local Docker socket or named pipe is permitted")
    return endpoint


def postgres(major):
    if major not in (17, 18):
        raise RuntimeError("PostgreSQL 18 or 17 required")
    env = environment()
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        try:
            endpoint = run(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], capture=True).stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise DockerUnavailable("Local Docker unavailable") from None
    prefix = ["docker", "--host", docker_transport(endpoint)]

    def docker(args, timeout=120):
        return run(prefix + args, env=env, timeout=timeout, capture=True).stdout.strip()

    try:
        docker(["info", "--format", "{{.ServerVersion}}"])
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise DockerUnavailable("Local Docker unavailable") from None
    identity = "fatwa-b6-" + uuid.uuid4().hex
    network, database, image = identity + "-net", identity + "-db", identity + ":qa"
    worker = identity + "-worker"
    created_network = created_database = built_image = created_worker = False
    try:
        # Install on the build network BEFORE attaching runtime to the internal network.
        # The build context contains only pinned requirements and this Dockerfile.
        with tempfile.TemporaryDirectory(prefix="fatwa-b6-build-") as directory:
            context = Path(directory)
            shutil.copyfile(ROOT / "requirements.txt", context / "requirements.txt")
            (context / "Dockerfile").write_text(
                "FROM python:3.13-slim-bookworm\nCOPY requirements.txt /tmp/requirements.txt\n"
                "RUN pip install --no-cache-dir -r /tmp/requirements.txt\n"
                "ENV PYTHONDONTWRITEBYTECODE=1\nWORKDIR /site\n", encoding="utf-8")
            docker(["build", "--tag", image, str(context)], timeout=600)
            built_image = True
        docker(["network", "create", "--internal", network])
        created_network = True
        # Cover the image's exact VOLUME declaration (changed in PG18) so Docker
        # cannot silently allocate an anonymous volume beneath a parent tmpfs.
        data_mount = "/var/lib/postgresql" if major == 18 else "/var/lib/postgresql/data"
        docker(["run", "--detach", "--name", database, "--network", network,
                "--tmpfs", data_mount + ":rw,nosuid,nodev,size=1073741824",
                "--env", "PGDATA=/var/lib/postgresql/data", "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
                "--env", "POSTGRES_DB=b6_ephemeral", "postgres:" + str(major) + "-bookworm"])
        created_database = True
        for attempt in range(60):
            try:
                docker(["exec", database, "pg_isready", "-U", "postgres", "-d", "b6_ephemeral"])
                break
            except subprocess.CalledProcessError:
                if attempt == 59:
                    raise RuntimeError("Ephemeral PostgreSQL readiness timed out") from None
                time.sleep(1)
        docker(["create", "--name", worker, "--network", network, "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--tmpfs", "/tmp",
                "--mount", "type=bind,source=" + str(ROOT) + ",target=/site,readonly",
                "--env", "PGHOST=" + database, "--env", "PGPORT=5432", "--env", "PGUSER=postgres",
                "--env", "PGDATABASE=b6_ephemeral", "--env", "PGTESTDATABASE=test_b6_ephemeral",
                "--env", "DJANGO_SETTINGS_MODULE=config.settings.test", "--env", "FATWA_PRODUCTION=0",
                image, "python", "tools/dev/qa_worker.py", str(major)])
        created_worker = True
        output = docker(["start", "--attach", worker], timeout=600)
        print(output)
        # docker start --attach does not reliably propagate the container exit code.
        exit_code = docker(["inspect", "--format", "{{.State.ExitCode}}", worker])
        if exit_code != "0":
            raise RuntimeError("Integrated Django/migration tests failed in isolated worker")
    finally:
        # Exact unique names only; no prune, compose down, volume removal, or live object actions.
        cleanup_errors = []
        for args, active in [(["rm", "--force", worker], created_worker),
                             (["rm", "--force", database], created_database),
                             (["network", "rm", network], created_network),
                             (["image", "rm", image], built_image)]:
            if active:
                try:
                    docker(args)
                except subprocess.CalledProcessError:
                    cleanup_errors.append(args[0])
        if cleanup_errors:
            raise RuntimeError("Ephemeral cleanup incomplete; inspect fatwa-b6 objects")


def node():
    files = sorted({str(p.relative_to(ROOT)) for folder in ["tests/dev", "tests/integration/ui"]
                    for p in (ROOT / folder).glob("*.test.mjs")})
    files.append("tests/integration/django-api.test.mjs")
    run(["node", "--test", *files])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["system", "postgres", "node", "all"])
    parser.add_argument("--postgres", type=int, choices=[17, 18], default=18)
    args = parser.parse_args()
    report = {"gates": "NOT_DEPLOYED / GATES_HOLD", "source_acceptance": "NOT_RUN",
              "browser": "NOT_RUN: Node DOM tests are not a real browser",
              "system": "NOT_RUN", "postgres": "NOT_RUN", "node": "NOT_RUN"}
    failed = False
    try:
        report.update(committed())
    except Exception:
        print("CI checkout verification failed; no suites executed")
        return 1
    for name, action in [("system", system), ("postgres", lambda: postgres(args.postgres)), ("node", node)]:
        if args.suite not in (name, "all"):
            continue
        try:
            action()
            report[name] = "PASS"
        except DockerUnavailable:
            report[name] = "NOT_RUN: Docker unavailable; migrations and database tests skipped"
            failed = True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError):
            # No captured Docker/driver output: these may contain connection details.
            report[name] = "FAIL_OR_UNAVAILABLE (not acceptance evidence)"
            failed = True
    print(json.dumps(report, indent=2))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
