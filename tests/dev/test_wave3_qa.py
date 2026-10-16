"""Synthetic dispatcher regressions; never connect to a database."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "wave3", Path(__file__).resolve().parents[2] / "tools/dev/wave3_qa.py")
wave3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wave3)


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="مجلد اختبار C6 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(wave3, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.checkout = patch.object(wave3.qa, "committed", return_value={"sha": "a" * 40})
        self.checkout.start()
        self.addCleanup(self.checkout.stop)

    def packages(self):
        for package in wave3.PACKAGES:
            folder = self.root / "tests" / package
            folder.mkdir(parents=True)
            (folder / "test_example.py").write_text("", encoding="utf-8")

    def test_absent_packages_are_not_pass(self):
        code, report = wave3.dispatch(standalone=True)
        self.assertEqual(code, 0)
        self.assertTrue(all(report[p].startswith("NOT_RUN") for p in wave3.PACKAGES))
        self.assertEqual(wave3.dispatch(standalone=True, require_integrated=True)[0], 1)

    def test_discovery_uses_explicit_python313_directories(self):
        self.packages()
        with patch.object(wave3.qa, "run") as run:
            code, report = wave3.dispatch(standalone=True, require_integrated=True)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable,
                         "tools/dev/wave3_discover.py", "tests/content_intake"])
        self.assertEqual(report["reference_links"], "PASS")

    def test_failure_continues_and_propagates(self):
        self.packages()
        for error in (FileNotFoundError(), subprocess.CalledProcessError(7, "python"),
                      subprocess.TimeoutExpired("python", 1)):
            with self.subTest(error=type(error).__name__), patch.object(
                    wave3.qa, "run", side_effect=[error, None, None]):
                code, report = wave3.dispatch(standalone=True)
                self.assertEqual(code, 1)
                self.assertTrue(report["content_intake"].startswith("FAIL"))
                self.assertEqual(report["reference_links"], "PASS")

    def test_wrong_python_runs_nothing(self):
        with patch.object(wave3.sys, "version_info", (3, 12)), patch.object(wave3.qa, "run") as run:
            self.assertEqual(wave3.dispatch()[0], 1)
        run.assert_not_called()

    def test_checkout_failure_runs_nothing(self):
        with patch.object(wave3.qa, "committed", side_effect=RuntimeError), patch.object(
                wave3.qa, "run") as run:
            self.assertEqual(wave3.dispatch()[0], 1)
        run.assert_not_called()

    def test_missing_django_and_node_propagate(self):
        with patch.object(wave3.qa, "run", side_effect=[None, subprocess.CalledProcessError(1, "check")]), patch.object(
                wave3.qa, "node", side_effect=FileNotFoundError):
            code, report = wave3.dispatch()
        self.assertEqual(code, 1)
        self.assertTrue(report["django"].startswith("FAIL"))
        self.assertTrue(report["node"].startswith("FAIL"))

    def test_only_read_only_default_commands(self):
        with patch.object(wave3.qa, "run") as run, patch.object(wave3.qa, "node"):
            wave3.dispatch()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn("check", commands[1])
        for command in commands:
            self.assertFalse({"migrate", "makemigrations", "postgres", "import"} & set(command))

    def test_real_unicode_path_subprocess(self):
        script = self.root / "فحص & test.py"
        script.write_text("print('unicode-ok')", encoding="utf-8")
        with patch.object(wave3.qa, "ROOT", self.root):
            result = wave3.qa.run([sys.executable, str(script)], capture=True)
        self.assertEqual(result.stdout.strip(), "unicode-ok")

    def test_real_discovery_empty_pass_and_failure(self):
        runner = Path(__file__).resolve().parents[2] / "tools/dev/wave3_discover.py"
        folder = self.root / "suite"
        folder.mkdir()
        for content, expected in [
            ("", 2),
            ("import unittest\nclass Example(unittest.TestCase):\n def test_ok(self): pass\n", 0),
            ("import unavailable_c6_dependency\n", 1),
        ]:
            with self.subTest(expected=expected):
                (folder / "test_synthetic.py").write_text(content, encoding="utf-8")
                result = subprocess.run([sys.executable, "-B", str(runner), str(folder)],
                                        capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_cmd_unicode_checkout_and_nonzero_exit(self):
        if os.name != "nt":
            self.skipTest("Windows CMD only")
        dev = self.root / "tools" / "dev"
        dev.mkdir(parents=True)
        source = Path(__file__).resolve().parents[2] / "tools/dev/TEST_WAVE3_LOCAL.cmd"
        (dev / source.name).write_bytes(source.read_bytes())
        (dev / "wave3_qa.py").write_text("raise SystemExit(7)", encoding="utf-8")
        env = dict(os.environ, FATWA_PYTHON=sys.executable, FATWA_NO_PAUSE="1")
        result = subprocess.run(["cmd", "/d", "/c", str(dev / source.name)],
                                cwd=self.root, env=env, capture_output=True)
        self.assertEqual(result.returncode, 7, result.stdout)
