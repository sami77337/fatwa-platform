"""Django test lifecycle for an explicitly owned Wave7 cluster; no unknown DB reuse."""
from django.core.management import call_command
from django.db import connections
from django.test.runner import DiscoverRunner
from psycopg import sql
from apps.intake_workflow.guards import (
    initialize_synthetic_database, require_synthetic_write, validate_write_configuration,
)


class Wave7TestRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        if suite.countTestCases() == 0:
            raise RuntimeError('Wave7 zero-case test suite rejected')
        return suite

    def setup_databases(self, **kwargs):
        if self.keepdb or self.parallel not in (0, 1):
            raise RuntimeError('Wave7 runner requires fresh single-process test databases')
        target = validate_write_configuration(synthetic_fixtures_only=True)
        require_synthetic_write(synthetic_fixtures_only=True)
        if target.database_name != target.base_name:
            raise RuntimeError('Wave7 test creation must start from its owned base database')
        connection = connections['default']
        self._wave7_created = None
        self._wave7_base = target.base_name
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname=%s', [target.test_name])
                if cursor.fetchone():
                    raise RuntimeError('Wave7 refuses any pre-existing test database; no drop or keepdb fallback')
                cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target.test_name)))
            self._wave7_created = target.test_name  # exact resource created by this invocation only
            connection.close()
            connection.settings_dict['NAME'] = target.test_name
            initialize_synthetic_database(synthetic_fixtures_only=True)
            call_command('migrate', verbosity=0, interactive=False, database='default')
        except Exception:
            self._wave7_cleanup()
            raise
        return [(connection, target.base_name, True)]

    def _wave7_cleanup(self):
        created = getattr(self, '_wave7_created', None)
        if created is None:
            return
        connection = connections['default']
        connection.close()
        connection.settings_dict['NAME'] = self._wave7_base
        require_synthetic_write(synthetic_fixtures_only=True)
        if created != 'test_' + self._wave7_base:
            raise RuntimeError('Wave7 exact-resource cleanup identity changed')
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(created)))
        self._wave7_created = None

    def teardown_databases(self, old_config, **kwargs):
        self._wave7_cleanup()
