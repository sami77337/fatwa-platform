"""Explicit nonzero Wave7 collections; DB labels never enter port-1 runners."""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SUITES = {
    'pure': (
        'tests.wave7_foundation.test_contracts',
        'tests.wave7_foundation.test_guard_config',
        'tests.wave7_foundation.test_lossless',
        'tests.wave7_foundation.test_integration_wiring',
        'tests.intake_workflow.test_check',
        'tests.intake_workflow.test_cli',
        'tests.acceptance.wave7.test_target',
        'tests.acceptance.wave7.test_entrypoints',
    ),
    'editorial-off': ('tests.editorial_demo.test_wave7_review_off',),
    'workflow-off': ('tests.integration.api.test_wave7_workflow_reads',),
    'database': (
        'tests.wave7_foundation.test_database',
        'tests.wave7_foundation.test_review_regressions',
        'tests.wave7_foundation.test_lossless_db',
        'tests.wave7_foundation.test_reference_service',
        'tests.wave7_foundation.test_service_integration',
        'tests.intake_workflow.test_database',
        'tests.editorial_demo.test_wave7_review_db',
        'tests.editorial_demo.test_wave7_read_db',
        'tests.integration.ui.wave7_workflow_reads_db',
    ),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=SUITES)
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--json', type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    report = dict(suite=args.suite, result='FAIL', modules=[], collected=0,
                  run=0, passed=0, failures=0, errors=0, skipped=0,
                  expected_failures=0, unexpected_successes=0, skips=[], skips_omitted=0,
                  source_acceptance='NOT_RUN', platform=sys.platform,
                  windows='EXECUTED' if sys.platform == 'win32' else 'NOT_RUN', gates='GATES_HOLD')
    try:
        if sys.version_info[:2] != (3, 13):
            raise RuntimeError('Python 3.13 required')
        from tools.dev.qa import committed, environment
        report.update(committed())
        report['python'] = sys.version.split()[0]
        if args.suite == 'database':
            if os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.settings.wave7_test':
                raise RuntimeError('Explicit Wave7 test profile required')
        else:
            clean = environment()
            clean['DJANGO_SETTINGS_MODULE'] = ('config.settings.test' if args.suite in ('editorial-off', 'workflow-off')
                                               else 'config.settings.wave7_test')
            os.environ.clear()
            os.environ.update(clean)
        import django
        django.setup()
        from django.test.runner import DiscoverRunner
        if args.suite == 'database':
            from apps.intake_workflow.guards import require_synthetic_write
            from tests.wave7_foundation.runner import Wave7TestRunner
            from django.db import connection
            context = require_synthetic_write(synthetic_fixtures_only=True)
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('server_version_num')::int")
                version = cursor.fetchone()[0]
            report['database'] = dict(name=context.database_name, postgres=version,
                                      scope=context.scope)
            runner_type = Wave7TestRunner
        else:
            runner_type = DiscoverRunner

        class ReportingRunner(runner_type):
            result = None

            def run_suite(self, suite, **kwargs):
                self.result = super().run_suite(suite, **kwargs)
                return self.result

        runner = ReportingRunner(verbosity=2, interactive=False)
        for label in SUITES[args.suite]:
            importlib.import_module(label)  # missing/invalid modules fail before execution
            count = runner.build_suite([label]).countTestCases()
            if count < 1:
                raise RuntimeError('Zero-case module rejected: ' + label)
            report['modules'].append(dict(label=label, collected=count))
            report['collected'] += count
        if args.collect_only:
            report['result'] = 'COLLECTED'
            return 0
        failures = runner.run_tests(list(SUITES[args.suite]))
        result = runner.result
        if result is None or result.testsRun != report['collected']:
            raise RuntimeError('Execution/collection count mismatch')
        report.update(run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                      skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
                      unexpected_successes=len(result.unexpectedSuccesses))
        report['skips'] = [dict(test=test.id()[:300], reason=str(reason)[:500])
                           for test, reason in result.skipped[:100]]
        report['skips_omitted'] = max(0, len(result.skipped) - 100)
        report['passed'] = max(0, result.testsRun - sum(report[key] for key in
            ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes')))
        report['result'] = 'FAIL' if failures or result.skipped or result.expectedFailures else 'PASS'
        return int(report['result'] != 'PASS')
    except Exception as error:
        # Fixed exception type only: no DB exception text/DSNs/source payloads.
        report['error_type'] = type(error).__name__
        print('Wave7 QA failed: ' + type(error).__name__, file=sys.stderr)
        return 1
    finally:
        report['duration_seconds'] = round(time.monotonic() - started, 3)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
