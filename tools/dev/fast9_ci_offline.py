"""Pinned FAST9 A+B offline evidence, never PostgreSQL/browser/CI acceptance.

Run: python -B tools/dev/fast9_ci_offline.py [--collect-only] [--json PATH]
Outputs and temporary sources are restricted to tests/dev/fast9_* in this
worktree. Git objects are read locally, without checkout, fetch or tree writes.
The composed manifest identifies a synthetic union, not an integrated commit.
"""

import argparse
import ast
import hashlib
import importlib.metadata
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BASE = "0769f66e93fdf710ca55e9e68e87430a93f14c40"
BASE_TREE = "38682aab5d845fe4b3bd99d79c6dd70b6dc4621e"
COMPOSED_SHA256 = "5307781abb51162f8414f715c6f38216bb4bb7b680c5a621216455bfc29f3a2f"
PINS = {
    152: (
        "7cf5e2986f6c2756414def5a20c503f36bf74f3a",
        "604b753c58834777a04a630de4a55ed4255c3113",
        "pg_fiqh_proof",
    ),
    153: (
        "c9319b98ea8df5f7ee3bc704f531b8f9eeb2bacc",
        "3cf7cfe86e27ae62c7fe70fd3e2a4ea959eebfca",
        "pg_workflow_audit",
    ),
    154: (
        "b0f9ee0be9a460cbc758a195995d9c86af26a3a3",
        "00d5b6c0b77d005c5696b0737721238fb150aeb0",
        "pg_reference_consistency",
    ),
    155: (
        "2a4800649573b50994016e128ca40b0a7cd9cc1f",
        "5c5dc70a6da1dbdc98975379ef51c861ca3024fc",
        "pg_browser_catalog",
    ),
    156: (
        "63511a56f31bd47ba2835010995227fa4403e2f1",
        "f8c9f757820f9cc22849ffa282cd54367690a0ef",
        "transcript_prepared_lineage",
    ),
    157: (
        "2d5cc49f883bf5611d7d64dca5c61696a16b7a08",
        "49c2a9b7307d92c72e37c1ab9d0c026e59c60769",
        "prepared_review_lineage",
    ),
    158: (
        "6801bcc6b3150cb45bce9a07bb86075c1b733698",
        "d53e4be39eff7ab288c90d9856d164c36183a955",
        "case_source_join",
    ),
    159: (
        "21f748d4a02a95c222ee0e3b11936706dda12bcd",
        "1c5a22ece7a1f50820f6ae32405c930095f5b591",
        "case_policy_join",
    ),
}


@dataclass(frozen=True)
class Suite:
    name: str
    pr: int
    modules: tuple[tuple[str, int], ...]
    kind: str = "python"

    @property
    def count(self):
        return sum(count for _, count in self.modules)


def python_suite(pr, *modules, suffix=""):
    name = PINS[pr][2]
    return Suite(
        name + suffix,
        pr,
        tuple((f"tests.fast9_{name}.{module}", count) for module, count in modules),
    )


SUITES = (
    python_suite(152, ("test_offline", 11)),
    python_suite(153, ("test_adapter", 21), ("test_cli", 4)),
    python_suite(154, ("test_django_adapter", 8), ("test_guard", 12), ("test_services", 14)),
    python_suite(155, ("test_guards", 22), suffix="_guards"),
    python_suite(155, ("test_http", 3), suffix="_http"),
    Suite(
        "pg_browser_catalog_policy",
        155,
        (("tests/fast9_pg_browser_catalog/policy.test.mjs", 3),),
        "node",
    ),
    python_suite(156, ("test_cli", 8), ("test_contracts", 4), ("test_services", 14)),
    python_suite(157, ("test_cli", 7), ("test_services", 12)),
    python_suite(158, ("test_cli", 5), ("test_preflight", 3), ("test_services", 15)),
    python_suite(159, ("test_adapters", 11), ("test_pg_guard", 2), ("test_services", 16)),
)
ZERO_FIELDS = (
    "failures",
    "errors",
    "skipped",
    "xfailed",
    "unexpected_successes",
    "todo",
    "cancelled",
)


class GuardError(RuntimeError):
    """A fixed local prerequisite, identity or execution check failed."""


def environment(inherited=None):
    # Allow only OS/process essentials. In particular no credentials, opt-ins,
    # CI markers, libpq service/pass files, Python/Node/Git injection variables.
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "PATHEXT",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "VIRTUAL_ENV",
    }
    clean = {
        k: v
        for k, v in (os.environ if inherited is None else inherited).items()
        if k.upper() in allowed
    }
    return clean | dict(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        FATWA_PRODUCTION="0",
        DJANGO_SETTINGS_MODULE="config.settings.test",
        PGHOST="127.0.0.1",
        PGPORT="1",
        PGDATABASE="fast9_offline_unreachable",
        PGUSER="fast9_offline_unreachable",
        PGPASSFILE=os.devnull,
        PGSERVICEFILE=os.devnull,
    )


def git(root, *args):
    env = environment() | {
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        env=env,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise GuardError("LOCAL_GIT_PREREQUISITE_FAILED")
    return result.stdout


def source_ref(root, pr):
    # Windows launchers keep a frozen alias. A fresh clone already has the
    # canonical PR branch. Either must resolve to the literal pinned commit.
    frozen = f"refs/remotes/origin/fatwa-v5-frozen-pr-{pr}"
    refs = git(root, "for-each-ref", "--format=%(refname)", frozen).decode().splitlines()
    if frozen in refs:
        return frozen
    lane = PINS[pr][2].replace("_", "-")
    return f"refs/remotes/origin/codex/20261027-fast9-{lane}-pc1"


def tree_manifest(root, sha):
    manifest = {}
    for row in git(root, "ls-tree", "-r", "-z", sha).split(b"\0"):
        if not row:
            continue
        meta, path = row.split(b"\t", 1)
        mode, kind, oid = meta.decode("ascii").split()
        if kind != "blob":
            raise GuardError("NON_BLOB_SOURCE")
        manifest[path.decode("utf-8")] = (mode, oid)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest):
    folded = set()
    for path, (mode, oid) in manifest.items():
        parts = PurePosixPath(path).parts
        if (
            not parts
            or path.startswith("/")
            or "\\" in path
            or ":" in path
            or any(
                p in (".", "..")
                or p.rstrip(" .") != p
                or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
                for p in path.split("/")
            )
            or mode not in ("100644", "100755")
            or not re.fullmatch("[a-f0-9]{40}", oid)
            or path.casefold() in folded
        ):
            raise GuardError("UNSAFE_SOURCE_PATH_OR_MODE")
        folded.add(path.casefold())


def compose_source(base, composed, incoming, pr):
    if any(incoming.get(path) != entry for path, entry in base.items()):
        raise GuardError("FAST8_SOURCE_CHANGED_OR_DELETED")
    additions = set(incoming) - set(base)
    prefixes = tuple(f"{area}/fast9_{PINS[pr][2]}/" for area in ("apps", "tools", "tests"))
    if not additions or any(
        not path.startswith(prefixes) or path in composed for path in additions
    ):
        raise GuardError("UNEXPECTED_OR_OVERLAPPING_LANE_PATH")
    composed.update({path: incoming[path] for path in additions})


def manifest_sha256(manifest):
    raw = "".join(
        f"{mode} blob {oid}\t{path}\n" for path, (mode, oid) in sorted(manifest.items())
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def inspect_sources(root):
    if git(root, "rev-parse", "--verify", BASE + "^{tree}").decode().strip() != BASE_TREE:
        raise GuardError("FAST8_TREE_MISMATCH")
    base = tree_manifest(root, BASE)
    composed = dict(base)
    sources = []
    for pr, (sha, tree, _) in PINS.items():
        ref = source_ref(root, pr)
        if git(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip() != sha:
            raise GuardError("FROZEN_REF_MISMATCH")
        if git(root, "rev-parse", "--verify", sha + "^{tree}").decode().strip() != tree:
            raise GuardError("PINNED_TREE_MISMATCH")
        git(root, "merge-base", "--is-ancestor", BASE, sha)
        incoming = tree_manifest(root, sha)
        compose_source(base, composed, incoming, pr)
        sources.append(dict(pr=pr, ref=ref, commit=sha, tree=tree, fast8_ancestor=True))
    validate_manifest(composed)
    if manifest_sha256(composed) != COMPOSED_SHA256:
        raise GuardError("COMPOSED_SOURCE_IDENTITY_MISMATCH")
    return composed, sources


def materialize(repo, manifest, destination):
    # Only repository code and bundled synthetic fixtures. No docs, archives,
    # user sources, Git metadata, hooks, workflows, dotenv or installed packages.
    selected = {
        p: e
        for p, e in manifest.items()
        if p.startswith(("apps/", "tools/", "tests/", "config/", "templates/"))
        and Path(p).suffix in (".py", ".mjs", ".json", ".csv", ".txt", ".html", ".css")
    }
    validate_manifest(selected)
    oids = sorted({oid for _, oid in selected.values()})
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), "cat-file", "--batch"],
        input=("\n".join(oids) + "\n").encode(),
        env=environment() | {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise GuardError("LOCAL_BLOBS_UNAVAILABLE")
    stream = io.BytesIO(result.stdout)
    blobs = {}
    for oid in oids:
        header = stream.readline().decode("ascii").split()
        if len(header) != 3 or header[:2] != [oid, "blob"]:
            raise GuardError("BLOB_PROTOCOL_MISMATCH")
        size = int(header[2])
        data = stream.read(size)
        actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if actual != oid or stream.read(1) != b"\n":
            raise GuardError("BLOB_IDENTITY_MISMATCH")
        blobs[oid] = data
    if stream.read():
        raise GuardError("EXTRA_BLOB_OUTPUT")
    for path, (_, oid) in selected.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blobs[oid])  # No text decoding/newline conversion.
    return selected


def definition_inventory(root):
    inventory = {}
    for suite in SUITES:
        ids = []
        for label, count in suite.modules:
            path = label if suite.kind == "node" else label.replace(".", "/") + ".py"
            raw = (root / path).read_bytes()
            if suite.kind == "node":
                found = re.findall(r'^test\("([^"\n]+)"', raw.decode("utf-8"), re.M)
            else:
                tree = ast.parse(raw)
                found = [
                    f"{label}.{cls.name}.{method.name}"
                    for cls in tree.body
                    if isinstance(cls, ast.ClassDef)
                    for method in cls.body
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and method.name.startswith("test")
                ]
            if len(found) != count or count <= 0 or len(set(found)) != count:
                raise GuardError("EXACT_DEFINITION_COUNT_MISMATCH")
            ids.extend(found)
        inventory[suite.name] = sorted(ids)
    if len(inventory) != 10 or sum(map(len, inventory.values())) != 195:
        raise GuardError("EXACT_TOTAL_MISMATCH")
    return inventory


GUARD = r"""
import os
import sys
from pathlib import Path
import subprocess

LOG = Path(os.environ['OFFLINE_COLLECTOR_GUARD_LOG'])
GUARD_PATH = os.environ['PYTHONPATH']

def deny(*args, **kwargs):
    with LOG.open('ab') as log:
        log.write(b'FAST9_OFFLINE_BLOCKED\n')
    raise RuntimeError('FAST9_OFFLINE_BLOCKED')

def audit(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo',
                 'os.system', 'os.spawn'):
        deny()
    if event in ('subprocess.Popen', 'os.posix_spawn'):
        if event == 'subprocess.Popen':
            executable, command, cwd, env = args
        else:
            executable, command, env = args
        if isinstance(command, str):
            permitted = any(command.startswith(subprocess.list2cmdline([sys.executable, '-B', flag]) + ' ')
                            for flag in ('-c', '-m'))
        else:
            permitted = (isinstance(command, (list, tuple)) and len(command) >= 4
                         and Path(command[0]).resolve() == Path(sys.executable).resolve()
                         and command[1:3] in (['-B', '-c'], ['-B', '-m']))
        if (not permitted or executable is not None
                and Path(executable).resolve() != Path(sys.executable).resolve()
                or env is None or env.get('PYTHONPATH') != GUARD_PATH
                or env.get('OFFLINE_COLLECTOR_GUARD_LOG') != str(LOG)):
            deny()

sys.addaudithook(audit)
try:
    import psycopg
    psycopg.connect = deny
    psycopg.Connection.connect = deny
    psycopg.AsyncConnection.connect = deny
except Exception:
    # CPython suppresses exceptions from sitecustomize and would run the child.
    try:
        deny()
    finally:
        os._exit(70)
"""


def install_guard(root):
    guard = root / "_offline_guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(GUARD, encoding="utf-8")


def worker_environment(root):
    scratch = root / "_scratch"
    scratch.mkdir(exist_ok=True)
    return environment() | dict(
        PYTHONPATH=str(root / "_offline_guard") + os.pathsep + str(root),
        OFFLINE_COLLECTOR_GUARD_LOG=str(root / "_guard_events"),
        TEMP=str(scratch),
        TMP=str(scratch),
        TMPDIR=str(scratch),
    )


def guard_events(root):
    path = root / "_guard_events"
    return path.read_bytes().splitlines() if path.exists() else []


def validate_counts(payload, expected):
    if type(expected) is not int or expected <= 0:
        raise GuardError("NONZERO_EXACT_COUNT_REQUIRED")
    for key in ("collected", "run", "passed", *ZERO_FIELDS):
        value = payload.get(key)
        if type(value) is not int or value != (0 if key in ZERO_FIELDS else expected):
            raise GuardError("EXECUTION_COUNT_OR_OUTCOME_MISMATCH")


def validate_python(payload, ids, exit_code):
    validate_counts(payload, len(ids))
    if (
        exit_code != 0
        or payload.get("status") != "PASS_OFFLINE"
        or payload.get("ids") != ids
        or sorted(payload.get("executed_ids", [])) != ids
    ):
        raise GuardError("PYTHON_EXECUTION_IDENTITY_MISMATCH")


def tap_counts(stdout):
    fields = {}
    required = {"tests", "suites", "pass", "fail", "cancelled", "skipped", "todo"}
    for line in stdout.splitlines():
        match = re.match(r"^# (\w+)\b(.*)$", line)
        if match and match[1] in required:
            key, value = match.groups()
            if key in fields or not re.fullmatch(r" [0-9]+", value):
                raise GuardError("TAP_INVALID_OR_DUPLICATE_SUMMARY")
            fields[key] = int(value)
    if fields.keys() != required:
        raise GuardError("TAP_MISSING_SUMMARY")
    return dict(
        collected=fields["tests"],
        run=fields["tests"],
        passed=fields["pass"],
        failures=fields["fail"],
        errors=0,
        xfailed=0,
        unexpected_successes=0,
        cancelled=fields["cancelled"],
        skipped=fields["skipped"],
        todo=fields["todo"],
    )


def parse_tap(stdout, exit_code, ids):
    payload = tap_counts(stdout)
    lines = stdout.splitlines()
    points = [line for line in lines if re.match(r"^(?:not ok|ok)\b", line)]
    executed_ids = []
    for number, point in enumerate(points, start=1):
        prefix = f"ok {number} - "
        if not point.startswith(prefix):
            raise GuardError("TAP_FAILED_OR_MISNUMBERED_POINT")
        executed_ids.append(point[len(prefix) :])
    if (
        exit_code != 0
        or [line for line in lines if line.startswith("1..")] != [f"1..{len(ids)}"]
        or "# suites 0" not in lines
        or any(line.startswith("Bail out!") for line in lines)
        or sorted(executed_ids) != ids
    ):
        raise GuardError("TAP_EXIT_PLAN_OR_OUTCOME_MISMATCH")
    validate_counts(payload, len(ids))
    return payload | {"executed_ids": executed_ids}


def aggregate(rows):
    if [row.get("name") for row in rows] != [suite.name for suite in SUITES]:
        raise GuardError("MISSING_DUPLICATE_OR_REORDERED_SUITE")
    for row, suite in zip(rows, SUITES, strict=True):
        if row.get("status") != "PASS_OFFLINE":
            raise GuardError("REQUIRED_SUITE_NOT_PASSED")
        validate_counts(row, suite.count)
    return "PASS_OFFLINE"


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def python_worker(root, spec, collect_only, output):
    """Internal fixed-label worker: unittest only, no DB runner lifecycle."""
    sys.path.insert(0, str(root))
    import django
    from django.test import SimpleTestCase, TransactionTestCase
    from django.test.utils import setup_test_environment, teardown_test_environment

    django.setup()
    loader = unittest.TestLoader()
    cases = []
    for label, expected in spec.modules:
        loaded = list(flatten(loader.loadTestsFromName(label)))
        if loader.errors or len(loaded) != expected:
            raise GuardError("RUNTIME_MODULE_COLLECTION_MISMATCH")
        for case in loaded:
            if (
                isinstance(case, TransactionTestCase)
                or isinstance(case, SimpleTestCase)
                and case.databases
            ):
                raise GuardError("DATABASE_TEST_FORBIDDEN")
        cases.extend(loaded)
    ids = sorted(case.id() for case in cases)
    if ids != definition_inventory(root)[spec.name]:
        raise GuardError("RUNTIME_DEFINITION_IDENTITY_MISMATCH")
    payload = dict(
        ids=ids,
        executed_ids=[],
        collected=len(cases),
        run=0,
        passed=0,
        status="COLLECTED",
        **dict.fromkeys(ZERO_FIELDS, 0),
    )
    if not collect_only:

        class Result(unittest.TextTestResult):
            def startTest(self, test):
                payload["executed_ids"].append(test.id())
                super().startTest(test)

            def addSuccess(self, test):
                payload["passed"] += 1
                super().addSuccess(test)

        setup_test_environment()
        try:
            result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(
                unittest.TestSuite(cases)
            )
        finally:
            teardown_test_environment()
        payload.update(
            run=result.testsRun,
            failures=len(result.failures),
            errors=len(result.errors),
            skipped=len(result.skipped),
            xfailed=len(result.expectedFailures),
            unexpected_successes=len(result.unexpectedSuccesses),
            status="PASS_OFFLINE"
            if (
                result.wasSuccessful()
                and result.testsRun == spec.count
                and payload["passed"] == spec.count
                and not result.skipped
                and not result.expectedFailures
            )
            else "FAIL",
        )
        # Preserve failing test identities and synthetic diagnostics in the local log.
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if not collect_only:
        validate_python(payload, ids, 0)


def execute_suite(root, spec, ids, collect_only):
    previous_events = len(guard_events(root))
    row = dict(
        name=spec.name,
        pr=spec.pr,
        expected=spec.count,
        status="NOT_RUN",
        collected=0,
        run=0,
        passed=0,
        **dict.fromkeys(ZERO_FIELDS, 0),
    )
    if spec.kind == "node" and collect_only:
        return row | dict(status="COLLECTED", collected=spec.count, ids=ids)
    env = worker_environment(root)
    output = root / f"_{spec.name}.json"
    if spec.kind == "python":
        command = [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--worker",
            spec.name,
            "--snapshot",
            str(root),
            "--output",
            str(output),
        ]
        if collect_only:
            command.append("--collect-only")
    else:
        command = ["node", "--test", "--test-reporter=tap", spec.modules[0][0]]
    try:
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
        row.update(
            exit_code=result.returncode,
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
        )
        if spec.kind == "python":
            if not output.exists():
                raise GuardError("WORKER_REPORT_MISSING")
            payload = json.loads(output.read_bytes())
            row.update(payload)
            if collect_only:
                if (
                    result.returncode
                    or payload["ids"] != ids
                    or payload["collected"] != spec.count
                    or payload["run"] != 0
                    or payload["status"] != "COLLECTED"
                ):
                    raise GuardError("COLLECTION_ONLY_MISMATCH")
            else:
                validate_python(payload, ids, result.returncode)
        else:
            # Retain observed counts even when exit status or an outcome fails.
            row.update(tap_counts(row["stdout"]))
            row.update(
                parse_tap(row["stdout"], result.returncode, ids),
                ids=ids,
                status="PASS_OFFLINE",
            )
        if len(guard_events(root)) != previous_events:
            raise GuardError("OFFLINE_GUARD_TRIGGERED")
    except (GuardError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        row.update(
            status="FAIL",
            reason=str(error) if isinstance(error, GuardError) else type(error).__name__,
        )
    return row


def owned_output(path):
    path = path.resolve()
    if (
        path.parent != ROOT / "tests" / "dev"
        or not path.name.startswith("fast9_")
        or path.suffix != ".json"
    ):
        raise GuardError("OUTPUT_OUTSIDE_OWNED_PATH")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    report = dict(
        status="FAIL",
        scope="LOCAL_PINNED_SYNTHETIC_OFFLINE_ONLY",
        baseline=BASE,
        baseline_tree=BASE_TREE,
        sources=[],
        suites=[],
        postgresql="NOT_RUN",
        browser="NOT_RUN",
        ci="NOT_RUN",
        deployment="NOT_DEPLOYED",
        source_owner_acceptance="NOT_CONNECTED",
        policy_acceptance="OWNER_APPROVAL_PENDING",
        gate_b="NOT_PASSED",
        gates_c_d_e="HOLD",
        phase01="BLOCKED",
        scope_gate="SCOPE_DEVIATION_HOLD",
        python=sys.version.split()[0],
    )
    output = None
    try:
        if args.json:
            output = owned_output(args.json)
        if sys.version_info[:2] != (3, 13):
            raise GuardError("PYTHON_3_13_REQUIRED")
        manifest, report["sources"] = inspect_sources(ROOT)
        report["source_manifest_sha256"] = manifest_sha256(manifest)
        report["source_identity_kind"] = "PINNED_GIT_OBJECT_UNION_NOT_INTEGRATED_COMMIT"
        report["local_head"] = git(ROOT, "rev-parse", "HEAD").decode().strip()
        report["collector_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["dependencies"] = {
            name: importlib.metadata.version(name) for name in ("Django", "psycopg", "django-htmx")
        }
        with tempfile.TemporaryDirectory(
            prefix="fast9_snapshot_", dir=ROOT / "tests" / "dev"
        ) as folder:
            root = Path(folder)
            selected = materialize(ROOT, manifest, root)
            report["materialized_file_count"] = len(selected)
            report["materialized_manifest_sha256"] = manifest_sha256(selected)
            report["fixtures"] = {
                path: dict(
                    git_blob=oid, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest()
                )
                for path, (_, oid) in selected.items()
                if path.startswith("tests/fast9_transcript_prepared_lineage/fixtures/")
            }
            inventory = definition_inventory(root)
            install_guard(root)
            report["node"] = subprocess.run(
                ["node", "--version"], env=environment(), capture_output=True, text=True, timeout=15
            ).stdout.strip()
            for spec in SUITES:
                print(f"FAST9 {spec.name}: expected={spec.count}", flush=True)
                report["suites"].append(
                    execute_suite(root, spec, inventory[spec.name], args.collect_only)
                )
            report["offline_guard_events"] = len(guard_events(root))
            # Tests may create/delete their own scratch files, but source bytes
            # must still match every materialized Git blob after execution.
            if any(
                hashlib.sha1(
                    f"blob {(root / p).stat().st_size}\0".encode() + (root / p).read_bytes()
                ).hexdigest()
                != oid
                for p, (_, oid) in selected.items()
            ):
                raise GuardError("SOURCE_BYTES_CHANGED_DURING_EXECUTION")
            if args.collect_only:
                if any(row["status"] != "COLLECTED" for row in report["suites"]):
                    raise GuardError("COLLECTION_FAILED")
                report["status"] = "COLLECTED"
            else:
                report["status"] = aggregate(report["suites"])
    except (
        GuardError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
        importlib.metadata.PackageNotFoundError,
    ) as error:
        report["reason"] = str(error) if isinstance(error, GuardError) else type(error).__name__
    report["duration_seconds"] = round(time.monotonic() - started, 3)
    report["collected"] = sum(row["collected"] for row in report["suites"])
    report["run"] = sum(row["run"] for row in report["suites"])
    report["passed"] = sum(row["passed"] for row in report["suites"])
    if output:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: report.get(key) for key in ("status", "collected", "run", "passed", "reason")}
        )
    )
    return int(report["status"] not in ("COLLECTED", "PASS_OFFLINE"))


if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker = argparse.ArgumentParser(allow_abbrev=False)
        worker.add_argument(
            "--worker", choices=[s.name for s in SUITES if s.kind == "python"], required=True
        )
        worker.add_argument("--snapshot", type=Path, required=True)
        worker.add_argument("--output", type=Path, required=True)
        worker.add_argument("--collect-only", action="store_true")
        opts = worker.parse_args()
        # A direct invocation cannot silently run without the inherited guard.
        if not os.environ.get("OFFLINE_COLLECTOR_GUARD_LOG") or "sitecustomize" not in sys.modules:
            raise GuardError("GUARDED_WORKER_REQUIRED")
        python_worker(
            opts.snapshot,
            next(s for s in SUITES if s.name == opts.worker),
            opts.collect_only,
            opts.output,
        )
    else:
        raise SystemExit(main())
