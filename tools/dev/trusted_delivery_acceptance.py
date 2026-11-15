"""Run the owned PostgreSQL acceptance suite; emit evidence and fail closed."""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MODULES = [
    'tests.delivery_queue.test_postgres_queue',
    'tests.delivery_queue.test_signed_approval_bridge',
    'tests.delivery_queue.test_postgres_audit_attestation',
    'tests.delivery_queue.test_queue_regressions',
    'tests.delivery_queue.test_trusted_journey',
    'tests.delivery_queue.test_delivery_reports',
]
MINIMUM_CASES = 55


def main():
    output = ROOT / '.local/qa/trusted-journey/result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {'status': 'ERROR', 'tests_run': 0, 'minimum_cases': MINIMUM_CASES,
               'test_ids': [], 'deployment': 'NOT_DEPLOYED', 'gates': 'HOLD'}
    result = None
    try:
        import django
        django.setup()
        from django.db import connection
        from tests.wave7_foundation.runner import Wave7TestRunner

        class RecordingResult(unittest.TextTestResult):
            def startTest(self, test):
                summary['test_ids'].append(test.id())
                super().startTest(test)

        class AcceptanceRunner(Wave7TestRunner):
            def get_resultclass(self):
                return RecordingResult

            def run_suite(self, suite, **kwargs):
                nonlocal result
                result = super().run_suite(suite, **kwargs)
                return result

        tested_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        summary['tested_sha'] = tested_sha
        summary['tested_tree'] = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
        expected_sha = os.environ.get('EXPECTED_SHA')
        if expected_sha and tested_sha != expected_sha:
            raise RuntimeError('unexpected_tested_revision')
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_setting('server_version_num')::int / 10000")
            database_name, major = cursor.fetchone()
        if major not in (17, 18) or not database_name.startswith('wave7_synthetic_'):
            raise RuntimeError('unexpected_test_database')
        summary['postgresql_major'] = major
        if str(major) != os.environ.get('PG_EXPECTED_MAJOR'):
            raise RuntimeError('unexpected_postgresql_major')
        failed = AcceptanceRunner(verbosity=2, interactive=False).run_tests(MODULES)
        summary.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
            skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
            unexpected_successes=len(result.unexpectedSuccesses))
        successful = (not failed and result.wasSuccessful() and result.testsRun >= MINIMUM_CASES
            and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses
            and len(summary['test_ids']) == len(set(summary['test_ids'])) == result.testsRun)
        summary['status'] = 'PASS' if successful else 'FAIL'
    except Exception as exc:
        summary['error_type'] = type(exc).__name__
        raise
    finally:
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('TRUSTED_DELIVERY_RESULT=' + json.dumps({key: value for key, value in summary.items() if key != 'test_ids'}, sort_keys=True))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
