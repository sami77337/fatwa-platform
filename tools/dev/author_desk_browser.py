"""Run the actual author desk browser scenario on the exact owned CI revision."""
from pathlib import Path
import json
import os
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import django
    django.setup()
    from django.db import connection
    from tests.wave7_foundation.runner import Wave7TestRunner
    output = ROOT / '.local/qa/trusted-journey/author-browser-result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {'status': 'ERROR', 'deployment': 'NOT_DEPLOYED'}
    result = None
    class Runner(Wave7TestRunner):
        def run_suite(self, suite, **kwargs):
            nonlocal result
            result = super().run_suite(suite, **kwargs)
            return result
    try:
        summary['tested_sha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if summary['tested_sha'] != os.environ['EXPECTED_SHA']:
            raise RuntimeError('unexpected_test_revision')
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::int / 10000")
            summary['postgresql_major'] = cursor.fetchone()[0]
        if str(summary['postgresql_major']) != os.environ['PG_EXPECTED_MAJOR']:
            raise RuntimeError('unexpected_postgresql_major')
        failure = Runner(verbosity=2, interactive=False).run_tests(['tests.delivery_queue.test_author_desk_browser'])
        summary.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
        summary['status'] = 'PASS' if not failure and result.wasSuccessful() and result.testsRun == 1 and not result.skipped else 'FAIL'
    finally:
        output.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print('AUTHOR_BROWSER_RESULT=' + json.dumps(summary, sort_keys=True))
    return 0 if summary['status'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
