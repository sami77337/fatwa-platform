"""Validate the integrated CI suite without executing database tests."""

from django.test import SimpleTestCase
from django.test.runner import DiscoverRunner

from tools.dev.qa import APP_TESTS


class IntegratedDiscoveryTests(SimpleTestCase):
    def test_wave2_suites_are_discoverable_and_included(self):
        suite = DiscoverRunner(verbosity=0).build_suite(APP_TESTS)

        def identifiers(group):
            for test in group:
                if hasattr(test, "__iter__"):
                    yield from identifiers(test)
                else:
                    yield test.id()

        names = list(identifiers(suite))
        self.assertFalse(any("_FailedTest" in name for name in names), names)
        for required in [
            "B2SearchTests", "CatalogTemplateTests", "AuditCommandTests",
            "B5PublicRegressionTests", "IntegratedSiteTests",
        ]:
            self.assertTrue(any(required in name for name in names), required)
