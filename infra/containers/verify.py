"""Build committed source and verify it in a constrained local Docker container."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE = "python:3.13-slim-bookworm"
PREFIX = "FATWA_CONTAINER_RESULT="


def output(*command):
    return subprocess.check_output(command, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", choices=("17", "18"), required=True)
    args = parser.parse_args()
    if shutil.which("docker") is None:
        parser.error("Docker is required; a source-only check is not runtime evidence")
    source = output("git", "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        parser.error("An exact committed source identity is required")
    if os.environ.get("EXPECTED_SHA", source) != source:
        parser.error("Requested source differs from this checkout")
    if output("git", "status", "--porcelain", "--untracked-files=normal"):
        parser.error("Commit the source before building the container")
    folder = Path(".local/qa/containers") / ("pg" + args.postgres)
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / "result.json"
    report_path.unlink(missing_ok=True)
    result = {"status": "RUNNING", "source_sha": source, "postgres_major": int(args.postgres)}
    container = None
    try:
        subprocess.run(["docker", "pull", BASE], check=True)
        base_metadata = json.loads(output("docker", "image", "inspect", BASE))[0]
        bases = [
            value
            for value in base_metadata["RepoDigests"]
            if re.fullmatch(r"python@sha256:[0-9a-f]{64}", value)
        ]
        if len(bases) != 1:
            raise RuntimeError("One immutable official Python image digest is required")
        base = bases[0]
        image_name = "fatwa-development:" + source[:12] + "-pg" + args.postgres
        with tempfile.TemporaryFile() as archive:
            # Only committed Git contents enter the build, never local credentials,
            # working copies, live DBs or host directories. Git metadata is absent.
            subprocess.run(["git", "archive", "--format=tar", source], stdout=archive, check=True)
            archive.seek(0)
            archive_hash = hashlib.file_digest(archive, "sha256").hexdigest()
            archive.seek(0)
            with (folder / "build.log").open("wb") as log:
                subprocess.run(
                    [
                        "docker",
                        "build",
                        "--file",
                        "infra/containers/Dockerfile",
                        "--build-arg",
                        "PYTHON_IMAGE=" + base,
                        "--build-arg",
                        "POSTGRES_MAJOR=" + args.postgres,
                        "--build-arg",
                        "SOURCE_REVISION=" + source,
                        "--tag",
                        image_name,
                        "-",
                    ],
                    stdin=archive,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=1200,
                )
        image = json.loads(output("docker", "image", "inspect", image_name))[0]
        if image["Config"]["Labels"]["org.opencontainers.image.revision"] != source:
            raise RuntimeError("Built image does not retain the requested source identity")
        container = output(
            "docker",
            "create",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "256",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777",
            "--tmpfs",
            "/app/.local:rw,nosuid,nodev,noexec,size=1g,uid=10001,gid=10001,mode=0700",
            image["Id"],
        )
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            raise RuntimeError("Unexpected container identity")
        inspected = json.loads(output("docker", "inspect", container))[0]
        host = inspected["HostConfig"]
        if (
            inspected["Config"]["User"] != "10001:10001"
            or host["NetworkMode"] != "none"
            or host["ReadonlyRootfs"] is not True
            or host["Privileged"] is not False
            or host["CapDrop"] != ["ALL"]
            or "no-new-privileges:true" not in host["SecurityOpt"]
            or host["Binds"]
            or host["PortBindings"]
        ):
            raise RuntimeError("Container does not have the required execution boundaries")
        with (folder / "runtime.log").open("wb") as log:
            subprocess.run(
                ["docker", "start", "--attach", container],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=900,
            )
        state = json.loads(output("docker", "inspect", container))[0]["State"]
        if state["ExitCode"] != 0 or state["OOMKilled"] or state["Running"]:
            raise RuntimeError("Container did not complete normally")
        text = (folder / "runtime.log").read_text()
        records = [
            json.loads(line[len(PREFIX) :]) for line in text.splitlines() if line.startswith(PREFIX)
        ]
        if (
            len(records) != 1
            or records[0].get("status") != "PASS"
            or records[0].get("source_sha") != source
        ):
            raise RuntimeError("Exact container runtime evidence is missing")
        result.update(
            status="PASS",
            source_archive_sha256=archive_hash,
            base_image=base,
            built_image_id=image["Id"],
            container_id=container,
            network="none",
            source_read_only=True,
            runtime=records[0],
            runtime_log_sha256=hashlib.sha256((folder / "runtime.log").read_bytes()).hexdigest(),
            build_log_sha256=hashlib.sha256((folder / "build.log").read_bytes()).hexdigest(),
            published_image=False,
            deployment="NOT_DEPLOYED",
        )
    except BaseException as exc:
        result.update(status="FAIL", failure_type=type(exc).__name__)
        raise
    finally:
        report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        if container and re.fullmatch(r"[0-9a-f]{64}", container):
            subprocess.run(
                ["docker", "rm", "--force", container], check=False, stdout=subprocess.DEVNULL
            )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
