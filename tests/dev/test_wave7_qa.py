"""Failures in one required module cannot be hidden by other green modules."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Wave7CollectionTests(unittest.TestCase):
    def probe(self, setup):
        with tempfile.TemporaryDirectory(prefix='wave7-e5-qa-') as folder:
            report = Path(folder, 'report.json')
            code = ('import sys, types, unittest\nfrom tools.dev import wave7_qa as qa\n'
                    + setup + '\nraise SystemExit(qa.main(["--suite","pure","--json",sys.argv[1]]))')
            result = subprocess.run([sys.executable, '-c', code, str(report)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
            return result.returncode, json.loads(report.read_text(encoding='utf-8'))

    def test_missing_required_module_fails_without_running_other_tests(self):
        status, report = self.probe("qa.SUITES['pure']=('tests.wave7_missing_required_module',)")
        self.assertNotEqual(status, 0)
        self.assertEqual((report['result'], report['run']), ('FAIL', 0))

    def test_zero_module_is_not_masked_by_nonzero_collection(self):
        status, report = self.probe("qa.SUITES['pure']=('tests.wave7_foundation.test_contracts','unittest')")
        self.assertNotEqual(status, 0)
        self.assertGreater(report['collected'], 0)
        self.assertEqual((report['result'], report['run']), ('FAIL', 0))

    def test_skipped_required_suite_is_not_a_pass(self):
        status, report = self.probe('''
module=types.ModuleType('wave7_e5_probe')
exec("import unittest\\nclass Probe(unittest.TestCase):\\n @unittest.skip('controlled missing gate')\\n def test_gate(self): pass\\n", module.__dict__)
sys.modules[module.__name__]=module
qa.SUITES['pure']=(module.__name__,)
''')
        self.assertNotEqual(status, 0)
        self.assertEqual((report['result'], report['run'], report['skipped']), ('FAIL', 1, 1))
        self.assertEqual(report['skips'][0]['reason'], 'controlled missing gate')

    def test_success_reports_actual_nonzero_execution_and_sha(self):
        status, report = self.probe('''
module=types.ModuleType('wave7_e5_probe')
exec("import unittest\\nclass Probe(unittest.TestCase):\\n def test_gate(self): self.assertEqual(73,73)\\n", module.__dict__)
sys.modules[module.__name__]=module
qa.SUITES['pure']=(module.__name__,)
''')
        self.assertEqual(status, 0)
        self.assertEqual((report['result'], report['collected'], report['run'], report['passed']), ('PASS', 1, 1, 1))
        self.assertRegex(report['sha'], r'^[a-f0-9]{40}$')
        self.assertEqual(report['source_acceptance'], 'NOT_RUN')
        self.assertEqual(report['platform'], sys.platform)
