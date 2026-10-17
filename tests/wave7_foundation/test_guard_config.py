import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.intake_workflow import contracts as c, guards as g


class GuardConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.database = dict(ENGINE='django.db.backends.postgresql', NAME='wave7_synthetic_probe',
            HOST='127.0.0.1', PORT='55487', USER=c.DATABASE_ROLE, PASSWORD='',
            TEST={'NAME': 'test_wave7_synthetic_probe'})
        self.settings = SimpleNamespace(DATABASES={'default': self.database},
            WAVE7_SCOPE=c.SYNTHETIC_SCOPE, WAVE7_SOURCE_CONFIG_ID=c.SOURCE_CONFIG_ID,
            WAVE7_BASE_DATABASE_NAME='wave7_synthetic_probe',
            WAVE7_TEST_DATABASE_NAME='test_wave7_synthetic_probe')
        self.env = patch.dict(os.environ, {'FATWA_WAVE7_SYNTHETIC_WRITES': '1', 'FATWA_PRODUCTION': '0'}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        setting = patch.object(g, 'settings', self.settings)
        setting.start(); self.addCleanup(setting.stop)

    def validate(self, **kwargs):
        return g.validate_write_configuration(synthetic_fixtures_only=True, **kwargs)

    def test_fixed_configuration_and_test_name_are_accepted_without_io(self):
        with patch.object(g, '_connection', side_effect=AssertionError('no I/O')):
            target = self.validate()
            self.assertEqual(target.scope, c.SYNTHETIC_SCOPE)
            self.database['NAME'] = self.database['TEST']['NAME']
            self.assertEqual(self.validate().database_name, 'test_wave7_synthetic_probe')

    def test_explicit_flags_and_literal_ack_reject_before_connection_or_atomic(self):
        cases = [{'FATWA_WAVE7_SYNTHETIC_WRITES': ''}, {'FATWA_WAVE7_SYNTHETIC_WRITES': 'true'},
                 {'FATWA_PRODUCTION': ''}, {'FATWA_PRODUCTION': '1'}]
        for changed in cases:
            with self.subTest(changed=changed), patch.dict(os.environ, changed), patch.object(g, '_connection') as conn:
                with self.assertRaises(g.SyntheticWriteDenied):
                    g.require_synthetic_write(synthetic_fixtures_only=True)
                conn.assert_not_called()
        for value in (False, None, 1, 'true'):
            with patch.object(g, '_connection') as conn, self.assertRaises(g.SyntheticWriteDenied):
                g.require_synthetic_write(synthetic_fixtures_only=value)
            conn.assert_not_called()

    def test_scope_and_source_config_are_fixed(self):
        for key in ('WAVE7_SCOPE', 'WAVE7_SOURCE_CONFIG_ID'):
            with patch.object(self.settings, key, 'caller-selected'), self.assertRaises(g.SyntheticWriteDenied):
                self.validate()

    def test_wrong_engine_host_name_role_test_target_and_port_reject(self):
        cases = [('ENGINE','django.db.backends.sqlite3'),('HOST','localhost'),('HOST','owner.invalid'),
                 ('NAME','fatwa_reference_dev'),('NAME','wave7_synthetic_other'),('USER','postgres'),
                 ('PORT','0'),('PORT','5432; bad'),('TEST',{'NAME':'test_owner_catalog'})]
        for key, value in cases:
            with self.subTest(key=key, value=value), patch.dict(self.database, {key:value}), self.assertRaises(g.SyntheticWriteDenied):
                self.validate()
        with self.assertRaises(g.SyntheticWriteDenied):
            self.validate(using='sibling')

    def test_inherited_connection_overrides_reject_without_driver_access(self):
        for key in ('DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGPASSFILE','PGOPTIONS'):
            with self.subTest(key=key), patch.dict(os.environ, {key:'synthetic-override'}), self.assertRaises(g.SyntheticWriteDenied):
                self.validate()

    def test_guard_never_begins_transaction_when_configuration_rejects(self):
        with patch.dict(os.environ, {'FATWA_WAVE7_SYNTHETIC_WRITES':'0'}), patch.object(g, 'transaction') as tx:
            with self.assertRaises(g.SyntheticWriteDenied):
                with g.synthetic_atomic(synthetic_fixtures_only=True):
                    self.fail('write body entered')
            tx.atomic.assert_not_called()

    def test_missing_flags_reject_before_any_connection(self):
        for missing in ('FATWA_WAVE7_SYNTHETIC_WRITES','FATWA_PRODUCTION'):
            original=dict(os.environ);original.pop(missing,None)
            with self.subTest(missing=missing),patch.dict(os.environ,original,clear=True),patch.object(g,'_connection') as conn:
                with self.assertRaises(g.SyntheticWriteDenied):
                    g.require_synthetic_write(synthetic_fixtures_only=True)
                conn.assert_not_called()

    def test_public_settings_and_middleware_do_not_register_workflow(self):
        from config.settings import base, test, wave7_development
        self.assertFalse(any('intake_workflow' in app for app in base.INSTALLED_APPS))
        self.assertFalse(any('intake_workflow' in app for app in test.INSTALLED_APPS))
        self.assertEqual(base.MIDDLEWARE,wave7_development.MIDDLEWARE)
        self.assertFalse(wave7_development.SENSITIVE_OPERATIONS_ENABLED)
        self.assertEqual(wave7_development.CATALOG_READ_ONLY,True)
        self.assertFalse(any('auth' in app or 'sessions' in app or 'admin' in app for app in wave7_development.INSTALLED_APPS))
