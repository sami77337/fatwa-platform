"""Fail closed before DB access; opt-in does not itself authorize an unknown DB."""

import contextlib
import io
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tools.fast9_pg_reference_consistency.__main__ import main
from tools.fast9_pg_reference_consistency.guard import (
    ACK,
    BASE_DATABASE,
    SETTINGS,
    TEST_DATABASE,
    PrerequisiteUnavailable,
    require_target,
    validate_environment,
)


def explicit_environment():
    return {
        "FAST9_PG_ACK": ACK,
        "FATWA_PRODUCTION": "0",
        "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
        "PGHOST": "127.0.0.1",
        "PGPORT": "60139",
        "PGUSER": "wave7_synthetic",
        "PGDATABASE": BASE_DATABASE,
        "PGTESTDATABASE": TEST_DATABASE,
        "PGPASSWORD": "fabricated-test-sentinel",
        "DJANGO_SETTINGS_MODULE": SETTINGS,
    }


def configured_database(name):
    return {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": "60139",
        "USER": "wave7_synthetic",
        "NAME": name,
        "PASSWORD": "fabricated-test-sentinel",
        "TEST": {"NAME": TEST_DATABASE},
    }


class GuardTests(TestCase):
    def test_explicit_configuration_is_only_configuration_evidence(self):
        self.assertIsNone(validate_environment(explicit_environment()))

    def test_every_required_configuration_field_is_required(self):
        for key in explicit_environment():
            environment = explicit_environment()
            del environment[key]
            with self.subTest(key=key), self.assertRaises(PrerequisiteUnavailable):
                validate_environment(environment)

    def test_default_owner_or_ambiguous_target_is_rejected(self):
        for key, value in (
            ("PGDATABASE", "fatwa_reference_dev"),
            ("PGTESTDATABASE", "test_fatwa_reference_dev"),
            ("PGHOST", "localhost"),
            ("PGUSER", "postgres"),
            ("FATWA_PRODUCTION", "1"),
            ("FAST9_PG_ACK", "1"),
            ("DJANGO_SETTINGS_MODULE", "config.settings.test"),
        ):
            with self.subTest(key=key), self.assertRaises(PrerequisiteUnavailable):
                validate_environment(explicit_environment() | {key: value})

    def test_protected_missing_and_invalid_ports_rejected(self):
        for port in ("", "1", "5432", "55432", "8000", "65536", "not-a-port", "٦٠١٣٩"):
            with self.subTest(port=port), self.assertRaises(PrerequisiteUnavailable):
                validate_environment(explicit_environment() | {"PGPORT": port})

    def test_inherited_overrides_rejected(self):
        for key in (
            "DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSFILE",
            "PGOPTIONS",
        ):
            with self.subTest(key=key), self.assertRaises(PrerequisiteUnavailable):
                validate_environment(explicit_environment() | {key: "forbidden-sentinel"})

    def test_default_command_reports_not_run_without_importing_or_connecting_django(self):
        with patch.dict(os.environ, {}, clear=True), patch("django.setup") as setup:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--postgresql"]), 2)
            setup.assert_not_called()
        self.assertIn('"postgresql": "NOT_RUN"', output.getvalue())

    def test_unavailable_owned_target_never_launches_test_runner(self):
        with (
            patch.dict(os.environ, explicit_environment(), clear=True),
            patch("django.setup"),
            patch(
                "tools.fast9_pg_reference_consistency.__main__.require_target",
                side_effect=PrerequisiteUnavailable("PRIVATE_SENTINEL"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(["--postgresql"]), 2)
        self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
        self.assertIn('"postgresql": "NOT_RUN"', output.getvalue())

    def test_postgresql_module_refuses_default_discovery_before_setup(self):
        script = """
from unittest.mock import patch
from django.db.backends.base.base import BaseDatabaseWrapper
with patch.object(BaseDatabaseWrapper, 'ensure_connection', side_effect=AssertionError('DB_CONNECT')):
    try:
        import tests.fast9_pg_reference_consistency.postgresql
    except RuntimeError as error:
        print(str(error))
    else:
        raise AssertionError('Unsafe discovery accepted')
"""
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PG", "FAST9_", "DJANGO_", "FATWA_"))
        }
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "EXPLICIT_SYNTHETIC_CONFIGURATION_REQUIRED")

    def test_exact_opt_in_collects_seven_pg_cases_without_connecting(self):
        script = """
import django
from unittest.mock import patch
from django.db.backends.base.base import BaseDatabaseWrapper
with patch.object(BaseDatabaseWrapper, 'ensure_connection', side_effect=AssertionError('DB_CONNECT')):
    django.setup()
    from tests.wave7_foundation.runner import Wave7TestRunner
    suite = Wave7TestRunner().build_suite(['tests.fast9_pg_reference_consistency.postgresql'])
    print('collected=' + str(suite.countTestCases()))
"""
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PG", "FAST9_", "DJANGO_", "FATWA_")) and key != "DATABASE_URL"
        }
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            env=environment | explicit_environment(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("collected=7", result.stdout)

    def test_runner_or_target_mismatch_rejected_before_ownership_query(self):
        import django
        from django.conf import settings

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        django.setup()
        target = SimpleNamespace(
            database_name="wrong", base_name=BASE_DATABASE, test_name=TEST_DATABASE
        )
        with (
            patch.dict(os.environ, explicit_environment(), clear=True),
            patch("apps.intake_workflow.guards.require_owned_database") as owned,
            patch("apps.intake_workflow.guards.validate_write_configuration", return_value=target),
            patch.object(settings, "TEST_RUNNER", "wrong"),
        ):
            with self.assertRaises(PrerequisiteUnavailable):
                require_target(test_database=False)
            owned.assert_not_called()
        with (
            patch.dict(os.environ, explicit_environment(), clear=True),
            patch("apps.intake_workflow.guards.require_owned_database") as owned,
            patch("apps.intake_workflow.guards.validate_write_configuration", return_value=target),
            patch.object(settings, "DATABASES", {"default": configured_database(TEST_DATABASE)}),
            patch(
                "django.db.connections",
                {"default": SimpleNamespace(settings_dict=configured_database(TEST_DATABASE))},
            ),
            patch.object(settings, "TEST_RUNNER", "tests.wave7_foundation.runner.Wave7TestRunner"),
        ):
            with self.assertRaises(PrerequisiteUnavailable):
                require_target(test_database=True)
            owned.assert_not_called()

    def test_actual_ownership_guard_is_required_for_each_exact_target(self):
        import django
        from django.conf import settings

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        django.setup()
        for is_test, name in ((False, BASE_DATABASE), (True, TEST_DATABASE)):
            target = SimpleNamespace(
                database_name=name, base_name=BASE_DATABASE, test_name=TEST_DATABASE
            )
            with (
                self.subTest(name=name),
                patch.dict(os.environ, explicit_environment(), clear=True),
                patch("apps.intake_workflow.guards.require_owned_database") as owned,
                patch(
                    "apps.intake_workflow.guards.validate_write_configuration", return_value=target
                ),
                patch.object(settings, "DATABASES", {"default": configured_database(name)}),
                patch(
                    "django.db.connections",
                    {"default": SimpleNamespace(settings_dict=configured_database(name))},
                ),
                patch.object(
                    settings, "TEST_RUNNER", "tests.wave7_foundation.runner.Wave7TestRunner"
                ),
            ):
                self.assertIs(require_target(test_database=is_test), owned.return_value)
                owned.assert_called_once_with(synthetic_fixtures_only=True)

    def test_stale_settings_or_cached_connection_rejected_before_ownership_query(self):
        import django
        from django.conf import settings

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        django.setup()
        for surface in ("settings", "connection"):
            for key, changed in (
                ("PORT", "5432"),
                ("PORT", "60140"),
                ("HOST", "localhost"),
                ("NAME", "fatwa_reference_dev"),
                ("USER", "postgres"),
                ("PASSWORD", "stale-synthetic"),
            ):
                configured = configured_database(BASE_DATABASE)
                effective = configured_database(BASE_DATABASE)
                (configured if surface == "settings" else effective)[key] = changed
                with (
                    self.subTest(surface=surface, field=key, changed=changed),
                    patch.dict(os.environ, explicit_environment(), clear=True),
                    patch("apps.intake_workflow.guards.require_owned_database") as owned,
                    patch.object(settings, "DATABASES", {"default": configured}),
                    patch(
                        "django.db.connections",
                        {"default": SimpleNamespace(settings_dict=effective)},
                    ),
                    patch.object(
                        settings, "TEST_RUNNER", "tests.wave7_foundation.runner.Wave7TestRunner"
                    ),
                ):
                    with self.assertRaisesRegex(
                        PrerequisiteUnavailable, "EFFECTIVE_CONNECTION_MISMATCH"
                    ):
                        require_target(test_database=False)
                    owned.assert_not_called()
