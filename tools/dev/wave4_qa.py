"""Wave4 explicit integration contract; no database or Docker actions."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa


def environment(root):
    return qa.environment() | {"PYTHONPATH": str(root), "PYTHONUTF8": "1"}


def execute(command, root, timeout=180):
    # Disk-backed output prevents unbounded RAM; only bounded tails enter JSON.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(command, cwd=root, env=environment(root), shell=False,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            code = result.returncode
            reason = "exit"
        except subprocess.TimeoutExpired:
            code, reason = 124, "timeout"
        except OSError:
            code, reason = 127, "unavailable"
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - 3000))
        tail = output.read().decode("utf-8", errors="replace")
    return {"status": "PASS" if code == 0 else "FAIL", "exit_code": code,
            "reason": reason, "output_tail": tail, "output_truncated": size > 3000}


def safe_path(root, value):
    path = (root / value).resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError("Paths must remain beneath project root")
    return path


def load_contract(root, manifest):
    if manifest.stat().st_size > 32768:
        raise ValueError("Manifest too large")
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if set(data) != {"D1", "D2", "D3", "D4", "D5"}:
        raise ValueError("Exactly D1-D5 required")
    for lane, entry in data.items():
        required = {"implementation", "python", "node"}
        if not required <= set(entry) or set(entry) - (required | {"django"}):
            raise ValueError("Invalid contract fields")
        for field in required:
            if not isinstance(entry[field], list) or len(entry[field]) > 20:
                raise ValueError("Expected bounded path lists")
            for value in entry[field]:
                if not isinstance(value, str) or len(value) > 240:
                    raise ValueError("Expected path string")
                safe_path(root, value)
        django_labels = entry.get("django", [])
        if not isinstance(django_labels, list) or len(django_labels) > 20:
            raise ValueError("Expected bounded Django labels")
        for label in django_labels:
            if not isinstance(label, str) or not re.fullmatch(
                r"tests(?:\\.[A-Za-z_][A-Za-z0-9_]*){2,}", label
            ):
                raise ValueError("Invalid Django test module")
            safe_path(root, label.replace(".", "/") + ".py")
        if not entry["implementation"] or not (entry["python"] or django_labels) or (
            lane == "D4" and not entry["node"]
        ):
            raise ValueError("Required implementation/tests/D4 Node entries missing")
    return data


def dispatch(root=ROOT, manifest=None, isolated=False, wave3=False):
    report = {"gates": "NOT_DEPLOYED / GATES_HOLD", "source_acceptance": "NOT_RUN",
              "postgres": "NOT_RUN: database access disabled", "suites": {}}
    if sys.version_info[:2] != (3, 13):
        report["preflight"] = "FAIL: Python 3.13 required"
        return 3, report
    try:
        contract = load_contract(root, manifest or root / "tools/dev/wave4_suites.json")
    except (OSError, ValueError, TypeError):
        report["preflight"] = "FAIL: invalid integration manifest"
        return 2, report
    failed, missing = False, False
    def run(name, args):
        nonlocal failed
        report["suites"][name] = execute(args, root)
        failed |= report["suites"][name]["status"] != "PASS"
    run("node_version", ["node", "--version"])
    run("django", [sys.executable, "manage.py", "check", "--settings=config.settings.test"])
    for lane, entry in contract.items():
        absent = []
        for value in entry["implementation"]:
            path = safe_path(root, value)
            if not path.exists() or (path.is_dir() and not any(
                    p.suffix in {".py", ".js", ".mjs", ".ts"} for p in path.rglob("*") if p.is_file())):
                absent.append(value)
        for value in entry["python"]:
            path = safe_path(root, value)
            if not path.is_dir() or not any(path.rglob("test*.py")):
                absent.append(value)
        for label in entry.get("django", []):
            if not safe_path(root, label.replace(".", "/") + ".py").is_file():
                absent.append(label)
        for value in entry["node"]:
            if not safe_path(root, value).is_file():
                absent.append(value)
        if absent:
            missing = True
            report["suites"][lane] = {"status": "NOT_RUN", "missing": absent}
            continue
        for index, value in enumerate(entry["python"]):
            run(f"{lane}.python.{index}", [sys.executable, str(root / "tools/dev/wave4_discover.py"), value])
        for index, label in enumerate(entry.get("django", [])):
            run(f"{lane}.django.{index}", [
                sys.executable, "manage.py", "test", label, "--noinput",
                "--settings=config.settings.test",
            ])
        if entry["node"]:
            # Node treats files with no registered tests as successful; wrapper checks TAP count.
            run(f"{lane}.node", [sys.executable, str(root / "tools/dev/wave4_node.py"), *entry["node"]])
    if wave3:
        run("wave3", [sys.executable, str(root / "tools/dev/wave3_qa.py"),
                      "--standalone", "--require-integrated"])
    report["acceptance"] = "FAIL" if failed else ("NOT_RUN" if missing else "PASS")
    return (1 if failed else 4 if missing and not isolated else 0), report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true", help="Allow absent lanes, report NOT_RUN")
    parser.add_argument("--wave3", action="store_true", help="Also require existing C1-C3 suites")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", type=Path, help="Save bounded summary")
    args = parser.parse_args(argv)
    code, report = dispatch(manifest=args.manifest, isolated=args.isolated, wave3=args.wave3)
    serialized = json.dumps(report, ensure_ascii=True, indent=2)
    print(serialized)
    if args.json:
        try:
            args.json.write_text(serialized + "\n", encoding="utf-8")
        except OSError:
            return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())


