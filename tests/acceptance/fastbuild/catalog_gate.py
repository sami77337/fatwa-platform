"""Explicit-only PostgreSQL gate; reuse existing E6 ownership and fixture guards."""

from apps.intake_workflow import fixtures, guards
from tests.acceptance.wave7.test_assets import E6LiveServer

from .test_browser import run_browser


class CatalogBrowserTests(E6LiveServer):
    def test_real_synthetic_postgresql_catalog(self):
        guards.require_synthetic_write(synthetic_fixtures_only=True)
        fixtures.seed_reference_catalog(synthetic_fixtures_only=True)
        self.assertEqual(run_browser(self.live_server_url, "catalog"), 0)
