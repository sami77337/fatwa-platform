"""No-DB default-off boundary; use ordinary test settings, never DB labels here."""
from unittest.mock import patch
from django.core.management import get_commands
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.urls import resolve, Resolver404
from apps.editorial_demo import views


class Wave7DefaultOffTests(SimpleTestCase):
    def test_persisted_route_and_cli_absent_from_default_settings(self):
        # The old generic preview route catches this segment as an unknown ID;
        # the separate persisted route must not be registered in default settings.
        self.assertNotEqual(resolve('/dev/editorial-preview/persisted').url_name, 'wave7_editorial_review')
        self.assertNotIn('wave7_review', get_commands())

    def test_direct_view_is_default_off_before_queries(self):
        request = RequestFactory().get('/dev/editorial-preview/persisted', HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
        response = views.persisted_review(request)
        self.assertEqual(response.status_code, 404)

    def test_unsafe_methods_reject_before_feature_or_database_processing(self):
        for method in ('post', 'put', 'patch', 'delete'):
            request = getattr(RequestFactory(), method)('/dev/editorial-preview/persisted', HTTP_HOST='localhost')
            self.assertEqual(views.persisted_review(request).status_code, 405)

    def test_legacy_worklist_is_unchanged(self):
        response = self.client.get('/dev/editorial-preview/pipeline', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SYN-P01')
        self.assertNotContains(response, 'wave7-persisted')
