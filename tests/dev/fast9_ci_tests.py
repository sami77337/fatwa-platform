"""Collector guards: exact pins/counts, failure evidence, and offline boundaries.

Local plan: inspect frozen Git objects; test refusal paths before implementation;
compose byte-exact synthetic sources under this owned directory; explicitly run
the ten approved suites; retain local evidence without changing shared CI.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.dev import fast9_ci_offline as ci

HERE = Path(__file__).resolve().parent


class ContractTests(unittest.TestCase):
    def test_manifest_has_ten_nonzero_suites_and_195_definitions(self):
        self.assertEqual(len(ci.SUITES), 10)
        self.assertEqual(sum(s.count for s in ci.SUITES), 195)
        self.assertTrue(all(s.count > 0 for s in ci.SUITES))
        self.assertEqual({s.pr for s in ci.SUITES}, set(range(152, 160)))
        self.assertEqual(len({s.name for s in ci.SUITES}), 10)

    def test_actual_pins_ancestor_trees_and_static_definitions(self):
        manifest, sources = ci.inspect_sources(ci.ROOT)
        self.assertEqual(ci.manifest_sha256(manifest), ci.COMPOSED_SHA256)
        self.assertEqual(len(sources), 8)
        self.assertTrue(all(s["fast8_ancestor"] is True for s in sources))
        with tempfile.TemporaryDirectory(prefix="fast9_static_", dir=HERE) as folder:
            root = Path(folder)
            ci.materialize(ci.ROOT, manifest, root)
            inventory = ci.definition_inventory(root)
            self.assertEqual(sum(len(ids) for ids in inventory.values()), 195)
            fixture = root / "tests/fast9_transcript_prepared_lineage/fixtures/manual-qa.json"
            pins = json.loads(fixture.with_name("manual-qa.pins.json").read_bytes())
            self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), pins["input_sha256"])
            self.assertFalse((root / ".git").exists())
            self.assertFalse((root / "docs").exists())

    def test_changed_frozen_ref_is_rejected(self):
        real = ci.git
        ref = ci.source_ref(ci.ROOT, 152)

        def changed(root, *args):
            if args == ("rev-parse", "--verify", ref + "^{commit}"):
                return b"0" * 40 + b"\n"
            return real(root, *args)

        with patch.object(ci, "git", side_effect=changed), self.assertRaises(ci.GuardError):
            ci.inspect_sources(ci.ROOT)

    def test_unknown_ancestor_is_rejected(self):
        real = ci.git

        def changed(root, *args):
            if args[0] == "merge-base":
                raise ci.GuardError("ANCESTRY_UNPROVEN")
            return real(root, *args)

        with patch.object(ci, "git", side_effect=changed), self.assertRaises(ci.GuardError):
            ci.inspect_sources(ci.ROOT)

    def test_missing_ref_and_wrong_source_tree_fail_before_materialization(self):
        real = ci.git
        ref = ci.source_ref(ci.ROOT, 152)
        for mode in ("missing", "tree"):

            def changed(root, *args):
                if mode == "missing" and args == (
                    "rev-parse",
                    "--verify",
                    ref + "^{commit}",
                ):
                    raise ci.GuardError("LOCAL_GIT_PREREQUISITE_FAILED")
                if mode == "tree" and args == (
                    "rev-parse",
                    "--verify",
                    ci.PINS[152][0] + "^{tree}",
                ):
                    return b"0" * 40 + b"\n"
                return real(root, *args)

            with (
                self.subTest(mode=mode),
                patch.object(ci, "git", side_effect=changed),
                self.assertRaises(ci.GuardError),
            ):
                ci.inspect_sources(ci.ROOT)

    def test_frozen_alias_takes_priority_over_canonical_pr_branch(self):
        frozen = "refs/remotes/origin/fatwa-v5-frozen-pr-152"
        with patch.object(ci, "git", return_value=frozen.encode() + b"\n"):
            self.assertEqual(ci.source_ref(ci.ROOT, 152), frozen)
        with patch.object(ci, "git", return_value=b""):
            self.assertEqual(
                ci.source_ref(ci.ROOT, 152),
                "refs/remotes/origin/codex/20261027-fast9-pg-fiqh-proof-pc1",
            )

    def test_missing_or_zero_case_module_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="fast9_zero_", dir=HERE) as folder:
            root = Path(folder)
            with self.assertRaises(FileNotFoundError):
                ci.definition_inventory(root)
            file = root / "tests/fast9_pg_fiqh_proof/test_offline.py"
            file.parent.mkdir(parents=True)
            file.write_text("import unittest\n", encoding="utf-8")
            with self.assertRaisesRegex(ci.GuardError, "EXACT_DEFINITION_COUNT_MISMATCH"):
                ci.definition_inventory(root)

    def test_report_cannot_replace_code_or_escape_owned_directory(self):
        for path in (ci.ROOT / "outside.json", HERE / "fast9_ci_tests.py", HERE / "unowned.json"):
            with self.subTest(path=path), self.assertRaises(ci.GuardError):
                ci.owned_output(path)

    def test_unsafe_paths_modes_and_case_collisions_rejected(self):
        for path in ("../escape", "/absolute", "a\\b", "C:/escape", "a/../b", "a/NUL"):
            with self.subTest(path=path), self.assertRaises(ci.GuardError):
                ci.validate_manifest({path: ("100644", "a" * 40)})
        with self.assertRaises(ci.GuardError):
            ci.validate_manifest({"apps/link": ("120000", "a" * 40)})
        with self.assertRaises(ci.GuardError):
            ci.validate_manifest(
                {"apps/A.py": ("100644", "a" * 40), "apps/a.py": ("100644", "b" * 40)}
            )

    def test_source_addition_cannot_replace_baseline_or_overlap_another_lane(self):
        base = {"apps/base.py": ("100644", "a" * 40)}
        for incoming in (
            {"apps/base.py": ("100644", "b" * 40)},
            {},
            {**base, "apps/foreign/file.py": ("100644", "b" * 40)},
        ):
            with self.subTest(incoming=incoming), self.assertRaises(ci.GuardError):
                ci.compose_source(base, dict(base), incoming, 152)


class ResultTests(unittest.TestCase):
    def valid(self):
        return dict(
            collected=2,
            run=2,
            passed=2,
            failures=0,
            errors=0,
            skipped=0,
            xfailed=0,
            unexpected_successes=0,
            todo=0,
            cancelled=0,
        )

    def test_nonzero_exact_execution_only(self):
        ci.validate_counts(self.valid(), 2)
        for key in self.valid():
            for value in (-1, True, "0", None, 0 if key in ("collected", "run", "passed") else 1):
                with self.subTest(key=key, value=value), self.assertRaises(ci.GuardError):
                    ci.validate_counts(self.valid() | {key: value}, 2)
        for expected in (0, -1, True):
            with self.assertRaises(ci.GuardError):
                ci.validate_counts(self.valid(), expected)

    def test_missing_field_is_not_defaulted_to_success(self):
        for key in self.valid():
            payload = self.valid()
            del payload[key]
            with self.subTest(key=key), self.assertRaises(ci.GuardError):
                ci.validate_counts(payload, 2)

    def test_python_ids_duplicates_errors_and_exit_disagreement_rejected(self):
        ids = ["synthetic.One.test_a", "synthetic.One.test_b"]
        good = self.valid() | dict(ids=ids, executed_ids=ids, status="PASS_OFFLINE")
        ci.validate_python(good, ids, 0)
        for payload, code in (
            (good, 1),
            (good | {"ids": ids[:1]}, 0),
            (good | {"executed_ids": [ids[0], ids[0]]}, 0),
            (good | {"status": "NOT_RUN"}, 0),
        ):
            with self.subTest(payload=payload, code=code), self.assertRaises(ci.GuardError):
                ci.validate_python(payload, ids, code)

    def test_tap_exact_pass_and_every_nonpass_state(self):
        ids = ["alpha", "bravo", "charlie"]
        points = "ok 1 - charlie\nok 2 - alpha\nok 3 - bravo\n"
        tap = (
            f"TAP version 13\n{points}1..3\n# tests 3\n# suites 0\n# pass 3\n# fail 0\n"
            "# cancelled 0\n# skipped 0\n# todo 0\n# duration_ms 2\n"
        )
        self.assertEqual(ci.parse_tap(tap, 0, ids)["passed"], 3)
        mutations = [
            tap.replace(points, ""),
            tap.replace("ok 1", "not ok 1"),
            tap.replace("ok 2", "ok 1"),
            tap.replace("alpha", "bravo"),
            tap.replace("alpha", "unknown point"),
            tap.replace("alpha", "alpha # TODO"),
            tap + "# fail unknown\n",
            tap + "1..unknown\n",
            tap + "Bail out!\n",
            tap.replace("# tests 3", "# tests 0"),
            tap.replace("1..3", "1..2"),
            tap + "# tests 3\n",
            tap.replace("# pass 3", "# pass 2"),
            tap.replace("# skipped 0", "# skipped 1"),
            tap.replace("# todo 0", "# todo 1"),
            tap.replace("# cancelled 0", "# cancelled 1"),
            tap + "ok 1 - hidden # SKIP reason\n",
            tap.replace("# fail 0\n", ""),
        ]
        for data in mutations:
            with self.subTest(data=data), self.assertRaises(ci.GuardError):
                ci.parse_tap(data, 0, ids)
        with self.assertRaises(ci.GuardError):
            ci.parse_tap(tap, 1, ids)

    def test_node_failure_retains_actual_executed_counts(self):
        tap = (
            b"TAP version 13\n1..3\n# tests 3\n# suites 0\n# pass 2\n# fail 1\n"
            b"# cancelled 0\n# skipped 0\n# todo 0\n"
        )
        completed = subprocess.CompletedProcess([], 1, stdout=tap, stderr=b"")
        with tempfile.TemporaryDirectory(prefix="fast9_node_failure_", dir=HERE) as folder:
            root = Path(folder)
            with patch.object(ci.subprocess, "run", return_value=completed):
                row = ci.execute_suite(root, ci.SUITES[5], ["one", "two", "three"], False)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual((row["run"], row["passed"], row["failures"]), (3, 2, 1))

    def test_aggregate_requires_every_exact_suite_once(self):
        rows = [dict(name=s.name, status="PASS_OFFLINE", **self.valid()) for s in ci.SUITES]
        for row, suite in zip(rows, ci.SUITES, strict=True):
            row.update(collected=suite.count, run=suite.count, passed=suite.count)
        self.assertEqual(ci.aggregate(rows), "PASS_OFFLINE")
        for changed in (rows[:-1], rows + [rows[0]], list(reversed(rows))):
            with self.assertRaises(ci.GuardError):
                ci.aggregate(changed)
        failed = copy.deepcopy(rows)
        failed[0]["status"] = "COLLECTED"
        with self.assertRaises(ci.GuardError):
            ci.aggregate(failed)


class OfflineGuardTests(unittest.TestCase):
    def test_failed_guard_installation_stops_child_before_application_code(self):
        with tempfile.TemporaryDirectory(prefix="fast9_guard_init_", dir=HERE) as folder:
            root = Path(folder)
            ci.install_guard(root)
            (root / "_offline_guard/psycopg.py").write_text(
                "raise RuntimeError('synthetic guard initialization failure')", encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", "print('APPLICATION_STARTED')"],
                cwd=root,
                env=ci.worker_environment(root),
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 70)
            self.assertNotIn(b"APPLICATION_STARTED", result.stdout)
            self.assertEqual(len(ci.guard_events(root)), 1)

    def test_original_fast9_environment_scrub_keeps_child_guard(self):
        with tempfile.TemporaryDirectory(prefix="fast9_scrub_", dir=HERE) as folder:
            root = Path(folder)
            ci.install_guard(root)
            script = """
import os, subprocess, sys
env = {k:v for k,v in os.environ.items()
       if not k.startswith(('PG', 'FAST9_', 'DJANGO_', 'FATWA_'))}
result = subprocess.run([sys.executable, '-B', '-c',
                        "import socket; socket.create_connection(('127.0.0.1',1))"],
                       env=env, capture_output=True)
assert result.returncode != 0
assert b'FAST9_OFFLINE_BLOCKED' in result.stderr
"""
            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=root,
                env=ci.worker_environment(root),
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(ci.guard_events(root)), 1)

    def test_real_worker_rejects_skip_xfail_unexpected_success_failure_and_error(self):
        probes = (
            ("@unittest.skip('synthetic')\n def test_case(self): pass", "skipped"),
            ("@unittest.expectedFailure\n def test_case(self): self.fail('synthetic')", "xfailed"),
            ("@unittest.expectedFailure\n def test_case(self): pass", "unexpected_successes"),
            ("def test_case(self): self.fail('synthetic')", "failures"),
            ("def test_case(self): raise ValueError('synthetic')", "errors"),
        )
        with tempfile.TemporaryDirectory(prefix="fast9_outcomes_", dir=HERE) as folder:
            root = Path(folder)
            ci.install_guard(root)
            for body, field in probes:
                output = root / "result.json"
                script = """
import sys, types, unittest
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools.dev import fast9_ci_offline as ci
module = types.ModuleType('synthetic_probe')
exec('import unittest\\nclass Probe(unittest.TestCase):\\n ' + sys.argv[4] + '\\n', module.__dict__)
sys.modules[module.__name__] = module
ids = ['synthetic_probe.Probe.test_case']
ci.definition_inventory = lambda root: {'probe': ids}
ci.python_worker(Path(sys.argv[2]), ci.Suite('probe', 152, (('synthetic_probe',1),)),
                 False, Path(sys.argv[3]))
"""
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        "-c",
                        script,
                        str(ci.ROOT),
                        str(root),
                        str(output),
                        body,
                    ],
                    cwd=root,
                    env=ci.worker_environment(root),
                    capture_output=True,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0, result.stderr)
                payload = json.loads(output.read_bytes())
                self.assertEqual(payload[field], 1, payload)
                self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(ci.guard_events(root))

    def test_direct_worker_without_guard_cannot_collect_or_run(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(ci.__file__)),
                "--worker",
                ci.SUITES[0].name,
                "--snapshot",
                str(HERE),
                "--output",
                str(HERE / "fast9_must_not_exist.json"),
            ],
            env=ci.environment(),
            capture_output=True,
            timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"GUARDED_WORKER_REQUIRED", result.stderr)
        self.assertFalse((HERE / "fast9_must_not_exist.json").exists())

    def test_environment_drops_credentials_optins_and_injection(self):
        inherited = dict(
            os.environ,
            PGPASSWORD="sentinel",
            PGHOSTADDR="foreign",
            FAST9_SYNTHETIC_PG="1",
            FATWA_WAVE7_SYNTHETIC_WRITES="1",
            GITHUB_TOKEN="sentinel",
            DATABASE_URL="sentinel",
            PYTHONPATH="foreign",
            NODE_OPTIONS="foreign",
            CI="true",
        )
        env = ci.environment(inherited)
        self.assertFalse(
            any(
                k in env
                for k in (
                    "PGPASSWORD",
                    "PGHOSTADDR",
                    "FAST9_SYNTHETIC_PG",
                    "GITHUB_TOKEN",
                    "DATABASE_URL",
                    "PYTHONPATH",
                    "NODE_OPTIONS",
                    "CI",
                )
            )
        )
        self.assertEqual(env["PGPORT"], "1")
        self.assertEqual(env["FATWA_PRODUCTION"], "0")

    def test_guard_blocks_native_postgres_network_browser_and_shell_before_io(self):
        with tempfile.TemporaryDirectory(prefix="fast9_guard_", dir=HERE) as folder:
            root = Path(folder)
            ci.install_guard(root)
            probes = (
                "import socket; socket.create_connection(('127.0.0.1',1))",
                "import psycopg; psycopg.connect('dbname=never_connect')",
                "import subprocess; subprocess.run(['browser-must-not-launch'])",
                "import os; os.system('must-not-launch')",
            )
            if hasattr(os, "posix_spawn"):
                probes += (
                    "import os; os.posix_spawn('/must-not-launch', ['must-not-launch'], os.environ)",
                    "import os,sys; os.posix_spawn(sys.executable, "
                    "[sys.executable, '-B', '-c', 'pass'], {})",
                )
            for code in probes:
                env = ci.worker_environment(root)
                result = subprocess.run(
                    [sys.executable, "-B", "-c", code],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"FAST9_OFFLINE_BLOCKED", result.stderr)
            self.assertTrue(ci.guard_events(root))


if __name__ == "__main__":
    unittest.main()
