"""Real discovery must disclose every module, zero cases, and skipped reasons."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools/dev/wave3_discover.py"


class CollectionEvidenceTests(unittest.TestCase):
    def run_suite(self, files):
        with tempfile.TemporaryDirectory(prefix="e5-collection-") as scratch:
            folder = Path(scratch) / "suite"
            folder.mkdir()
            for name, content in files.items():
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            report = Path(scratch) / "summary.json"
            result = subprocess.run([sys.executable, "-B", str(RUNNER), str(folder),
                                     "--json", str(report)], cwd=ROOT, capture_output=True)
            self.assertTrue(report.is_file(), result.stderr.decode())
            return result.returncode, json.loads(report.read_text(encoding="utf-8"))

    def test_actual_counts_modules_and_skips(self):
        code, report = self.run_suite({"test_example.py":
            "import unittest\nclass T(unittest.TestCase):\n"
            " def test_good(self): pass\n"
            " @unittest.skip('synthetic missing source')\n def test_source(self): pass\n"})
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"], {"collected": 2, "run": 2, "passed": 1,
                                          "failures": 0, "errors": 0, "skipped": 1,
                                          "expected_failures": 0, "unexpected_successes": 0})
        self.assertEqual(report["modules"], {"test_example.py": 2})
        self.assertEqual(report["skips"][0]["reason"], "synthetic missing source")
        self.assertRegex(report["sha"], r"^[a-f0-9]{40}$")

    def test_zero_case_module_cannot_hide_among_passing_modules(self):
        code, report = self.run_suite({"test_empty.py": "", "test_good.py":
            "import unittest\nclass T(unittest.TestCase):\n def test_good(self): pass\n"})
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["uncollected_modules"], ["test_empty.py"])

    def test_namespace_nested_module_cannot_disappear(self):
        code, report = self.run_suite({"nested/test_hidden.py":
            "import unittest\nclass T(unittest.TestCase):\n def test_hidden(self): pass\n"})
        self.assertNotEqual(code, 0)
        self.assertIn("nested/test_hidden.py", report["uncollected_modules"])

    def test_import_failure_is_a_failure_with_no_false_pass(self):
        code, report = self.run_suite({"test_broken.py": "import absent_e5_dependency\n"})
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["counts"]["errors"], 1)

    def test_full_importer_is_required_in_pure_dispatch(self):
        from tools.dev import wave3_qa
        self.assertIn("fiqh_import", wave3_qa.PACKAGES)

    def test_expected_importer_inventory(self):
        expected = {"test_book622_verification.py", "test_catalog_audit.py",
                    "test_citation_audit.py", "test_ingest.py", "test_owner_adapter.py",
                    "test_owner_source.py", "test_fixture_bytes.py"}
        actual = {str(p.relative_to(ROOT / "tests/fiqh_import"))
                  for p in (ROOT / "tests/fiqh_import").rglob("test*.py")}
        self.assertEqual(actual, expected)


class DjangoCommandCollectionTests(unittest.TestCase):
    def test_django_command_zero_cases_fail_and_real_case_count_is_recorded(self):
        from tools.dev.wave4_qa import execute
        with tempfile.TemporaryDirectory(prefix="e5-django-count-") as scratch:
            root = Path(scratch)
            script = root / "manage.py"
            for body, expected, count in [
                ("", 2, 0),
                ("class T(unittest.TestCase):\n def test_one(self): pass\n", 0, 1),
            ]:
                script.write_text("import unittest, sys\n" + body +
                    "suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])\n"
                    "result = unittest.TextTestRunner().run(suite)\n"
                    "raise SystemExit(not result.wasSuccessful())\n", encoding="utf-8")
                result = execute([sys.executable, "manage.py", "test"], root)
                self.assertEqual(result["exit_code"], expected, result)
                self.assertEqual(result["counts"]["run"], count)
