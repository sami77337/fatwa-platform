"""D6 real subprocess and synthetic integrated-checkout regressions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("wave4", ROOT / "tools/dev/wave4_qa.py")
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


class Wave4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="اختبار D6 spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = {f"D{i}": {"implementation": [f"impl/d{i}.py"],
                         "python": [f"tests/d{i}"],
                         "node": ["tests/d4/functional.test.mjs"] if i == 4 else []}
                         for i in range(1, 6)}
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(self.contract), encoding="utf-8")

    def populate(self):
        for entry in self.contract.values():
            for value in entry["implementation"] + entry["node"]:
                p = self.root / value
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# synthetic", encoding="utf-8")
            for value in entry["python"]:
                p = self.root / value
                p.mkdir(parents=True, exist_ok=True)
                (p / "test_ok.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n")

    def dispatch(self, **kwargs):
        return w.dispatch(self.root, self.manifest, **kwargs)

    def test_absent_required(self):
        with patch.object(w, "execute", return_value={"status": "PASS"}):
            code, report = self.dispatch()
        self.assertEqual(code, 4)
        self.assertEqual(report["acceptance"], "NOT_RUN")
        self.assertEqual(report["suites"]["D1"]["status"], "NOT_RUN")

    def test_isolated_does_not_claim_acceptance(self):
        with patch.object(w, "execute", return_value={"status": "PASS"}):
            code, report = self.dispatch(isolated=True)
        self.assertEqual(code, 0)
        self.assertEqual(report["acceptance"], "NOT_RUN")

    def test_integrated_explicit_commands(self):
        self.populate()
        with patch.object(w, "execute", return_value={"status": "PASS"}) as run:
            code, report = self.dispatch()
        self.assertEqual(code, 0)
        self.assertEqual(report["acceptance"], "PASS")
        self.assertEqual(run.call_count, 8)
        self.assertIn("tests/d1", run.call_args_list[2].args[0])
        self.assertIn("wave4_node.py", run.call_args_list[6].args[0][1])

    def test_implementation_missing_even_with_tests(self):
        self.populate()
        (self.root / "impl/d2.py").unlink()
        with patch.object(w, "execute", return_value={"status": "PASS"}):
            self.assertEqual(self.dispatch()[0], 4)

    def test_empty_tests_rejected(self):
        self.populate()
        (self.root / "tests/d1/test_ok.py").unlink()
        with patch.object(w, "execute", return_value={"status": "PASS"}):
            self.assertEqual(self.dispatch()[0], 4)

    def test_wrong_python_no_subprocess(self):
        with patch.object(w.sys, "version_info", (3, 12)), patch.object(w, "execute") as run:
            self.assertEqual(self.dispatch()[0], 3)
        run.assert_not_called()

    def test_invalid_manifest_and_escape(self):
        for data in ({}, self.contract | {"D6": {}}, {k: v | {"implementation": ["../escape"]} for k, v in self.contract.items()}):
            self.manifest.write_text(json.dumps(data))
            self.assertEqual(self.dispatch()[0], 2)

    def test_failure_continues(self):
        self.populate()
        with patch.object(w, "execute", side_effect=[{"status": "FAIL"}] + [{"status": "PASS"}] * 7) as run:
            self.assertEqual(self.dispatch()[0], 1)
        self.assertEqual(run.call_count, 8)

    def test_subprocess_codes_and_bounded_output(self):
        for expression, code in [("print('x'*20000)", 0), ("raise SystemExit(9)", 9)]:
            result = w.execute([sys.executable, "-c", expression], self.root)
            self.assertEqual(result["exit_code"], code)
            self.assertLessEqual(len(result["output_tail"]), 3000)
        self.assertEqual(w.execute([str(self.root / "absent.exe")], self.root)["exit_code"], 127)
        self.assertEqual(w.execute([sys.executable, "-c", "import time; time.sleep(3)"], self.root, .01)["exit_code"], 124)

    def test_unicode_space_path_and_shell_false(self):
        script = self.root / "فحص & test.py"
        script.write_text("print('ok')")
        self.assertEqual(w.execute([sys.executable, str(script)], self.root)["status"], "PASS")
        with patch.object(w.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            w.execute([sys.executable, str(script)], self.root)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONPATH"], str(self.root))
        self.assertEqual(run.call_args.kwargs["env"]["PGPORT"], "1")

    def test_real_python_discovery_lf_crlf_zero_and_failure(self):
        folder = self.root / "suite"
        folder.mkdir()
        file = folder / "test_ok.py"
        for data, expected in [(b"", 2), (b"import nonexistent_d6_module\n", 1),
            (b"import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n", 0)]:
            for newline in (b"\n", b"\r\n"):
                original = data.replace(b"\n", newline)
                file.write_bytes(original)
                result = w.execute([sys.executable, "-B", str(ROOT / "tools/dev/wave3_discover.py"), str(folder)], self.root)
                self.assertEqual(result["exit_code"], expected, result)
                self.assertEqual(file.read_bytes(), original)

    def test_real_node_zero_failure_and_good(self):
        file = self.root / "functional.test.mjs"
        for content, expected in [("", 2), ("throw Error('synthetic')", 1),
                ("import test from 'node:test'; test('ok',()=>{});", 0)]:
            file.write_text(content)
            result = w.execute([sys.executable, str(ROOT / "tools/dev/wave4_node.py"), str(file)], self.root)
            self.assertEqual(result["exit_code"], expected, result)

    def test_cli_options_and_invalid_argument(self):
        with patch.object(w, "dispatch", return_value=(4, {"acceptance": "NOT_RUN"})) as run:
            self.assertEqual(w.main(["--isolated", "--wave3", "--manifest", str(self.manifest)]), 4)
        self.assertTrue(run.call_args.kwargs["isolated"])
        with self.assertRaises(SystemExit) as raised:
            w.main(["--unknown"])
        self.assertEqual(raised.exception.code, 2)

    @unittest.skipUnless(os.name == "nt", "Windows CMD")
    def test_cmd_propagates_failure_unicode_path(self):
        dev = self.root / "tools/dev"
        dev.mkdir(parents=True)
        launcher = dev / "TEST_WAVE4_LOCAL.cmd"
        launcher.write_bytes((ROOT / "tools/dev/TEST_WAVE4_LOCAL.cmd").read_bytes())
        (dev / "wave4_qa.py").write_text("raise SystemExit(7)")
        result = subprocess.run(["cmd", "/d", "/c", str(launcher)], capture_output=True,
                                env=dict(os.environ, FATWA_PYTHON=sys.executable, FATWA_NO_PAUSE="1"))
        self.assertEqual(result.returncode, 7, result.stdout)

    def test_real_complete_synthetic_integration(self):
        self.populate()
        dev = self.root / 'tools/dev'
        dev.mkdir(parents=True)
        for name in ('wave4_discover.py', 'wave3_discover.py', 'wave4_node.py', 'wave4_reporter.mjs'):
            (dev / name).write_bytes((ROOT / 'tools/dev' / name).read_bytes())
        (self.root / 'manage.py').write_text("print('synthetic system checker')")
        (self.root / 'tests/d4/functional.test.mjs').write_text("import test from 'node:test'; test('synthetic',()=>{});")
        code, report = self.dispatch()
        self.assertEqual(code, 0, report)
        self.assertEqual(report['acceptance'], 'PASS')
        # An empty nested namespace directory must not disappear from collection.
        nested = self.root / 'tests/d1/nested'
        nested.mkdir()
        (nested / 'test_empty.py').write_text('')
        code, report = self.dispatch()
        self.assertEqual(code, 1, report)
        self.assertEqual(report['suites']['D1.python.0']['status'], 'FAIL')

    def test_existing_good_python_and_node_modules(self):
        for command in ([sys.executable, str(ROOT / 'tools/dev/wave4_discover.py'),
                         str(ROOT / 'tests/fatwa_drafts')],
                        [sys.executable, str(ROOT / 'tools/dev/wave4_node.py'),
                         str(ROOT / 'tests/dev/health.test.mjs')]):
            result = w.execute(command, ROOT)
            self.assertEqual(result['exit_code'], 0, result)
