"""Wave7 E4 no-DB/default-off read contract. URLConf is TEST-ONLY."""
import os
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings
from django.urls import path

from apps.reference import services, views
from apps.reference.query import InvalidQuery, Page


def items_view(request):
    return views.api_workflow_items(request)


def batches_view(request):
    return views.api_workflow_batches(request)


def detail_view(request, ident):
    return views.api_workflow_item(request, ident)


urlpatterns = [
    path('dev/wave7/api/items', items_view),
    path('dev/wave7/api/batches', batches_view),
    path('dev/wave7/api/items/<str:ident>', detail_view),
]


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class Wave7ReadContractTests(SimpleTestCase):
    def test_required_services_and_context_exist(self):
        for module, names in ((services, ('workflow_items', 'workflow_batches', 'workflow_item')),
                              (views, ('workflow_read_context', 'api_workflow_items',
                                       'api_workflow_batches', 'api_workflow_item'))):
            for name in names:
                self.assertTrue(callable(getattr(module, name, None)), name)

    def test_default_off_services_never_open_a_database(self):
        for name, args in (('workflow_items', ()), ('workflow_batches', ()), ('workflow_item', (uuid4(),))):
            with self.subTest(name=name):
                with self.assertRaises(services.WorkflowReadsDisabled):
                    getattr(services, name)(*args, synthetic_fixtures_only=True)

    @override_settings(ROOT_URLCONF=__name__)
    def test_unwired_by_default_and_disabled_test_routes_are_json_404(self):
        for path in ('/dev/wave7/api/items', '/dev/wave7/api/batches', '/dev/wave7/api/items/'+str(uuid4())):
            response = self.client.get(path, HTTP_HOST='127.0.0.1')
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()['error'], 'not_found')
            self.assertNotIn(b'Traceback', response.content)
            self.assertEqual(self.client.head(path, HTTP_HOST='127.0.0.1').content, b'')

    @override_settings(ROOT_URLCONF='config.urls')
    def test_actual_legacy_urlconf_does_not_wire_wave7(self):
        self.assertEqual(self.client.get('/dev/wave7/api/items').status_code, 404)

    def test_service_rejects_bad_filters_and_identifiers_before_guard(self):
        queries = [dict(text='x'*161), dict(text='a '*11), dict(text='x\x00'),
                   dict(text='x\ud800'), dict(mode='semantic'), dict(mode=[]),
                   dict(intake_status='approved'), dict(review_status='published'),
                   dict(batch_id='../../elsewhere'), dict(batch_id=73), dict(page=(20, 0))]
        with patch('apps.reference.services._require_workflow_read') as guard:
            for query in queries:
                with self.subTest(query=repr(query)), self.assertRaises(InvalidQuery):
                    services.workflow_items(**query, synthetic_fixtures_only=True)
            guard.assert_not_called()

    @override_settings(ROOT_URLCONF=__name__, WAVE7_READS_ENABLED=True)
    def test_api_invalid_params_are_json_without_service_or_db(self):
        with patch('apps.reference.services._workflow_reads_enabled', return_value=True), \
             patch('apps.reference.services.workflow_items') as reader:
            for query in ('q=x&q=x', 'unknown=1', 'limit=0', 'limit=101', 'offset=20001',
                          'batch=not-a-uuid', 'intake_status=approved', 'review_status=published',
                          'mode=semantic', '&'.join('q=x' for _ in range(17))):
                response = self.client.get('/dev/wave7/api/items?'+query, HTTP_HOST='127.0.0.1')
                self.assertEqual(response.status_code, 400, query)
                self.assertEqual(response.json()['error'], 'invalid_query')
            reader.assert_not_called()

    @override_settings(ROOT_URLCONF=__name__, WAVE7_READS_ENABLED=True)
    def test_method_and_loopback_fail_closed(self):
        with patch('apps.reference.services._workflow_reads_enabled', return_value=True), \
             patch('apps.reference.services.workflow_items') as reader:
            for method in ('post', 'put', 'patch', 'delete'):
                self.assertEqual(getattr(self.client, method)('/dev/wave7/api/items', HTTP_HOST='127.0.0.1').status_code, 405)
            self.assertEqual(self.client.get('/dev/wave7/api/items', HTTP_HOST='127.0.0.1', REMOTE_ADDR='203.0.113.9').status_code, 404)
            reader.assert_not_called()

    @override_settings(ROOT_URLCONF=__name__, WAVE7_READS_ENABLED=True)
    def test_database_errors_are_redacted(self):
        with patch('apps.reference.services._workflow_reads_enabled', return_value=True), \
             patch('apps.reference.services.workflow_items', side_effect=services.WorkflowReadUnavailable()):
            response = self.client.get('/dev/wave7/api/items', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'workflow_unavailable')
