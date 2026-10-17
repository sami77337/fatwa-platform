"""Actual E1 -> committed E3 -> E2 read, through the shared Wave7 URLconf."""
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.intake_workflow import fixtures as f, guards as g
from apps.intake_workflow.intake import import_intake
from apps.intake_workflow.models import IntakeItem, IntakeReference, ReviewEvent
from apps.intake_workflow.references import verify_batch_references
from apps.intake_workflow.review import transition_review
from apps.reference import views as reference_views


class ServiceIntegrationTests(TransactionTestCase):
    def setUp(self):
        g.require_synthetic_write(synthetic_fixtures_only=True)
        f.seed_reference_catalog(synthetic_fixtures_only=True)
        self.receipt = import_intake(f.synthetic_payload(), idempotency_key=uuid4().hex,
                                    synthetic_fixtures_only=True)
        self.row = IntakeItem.objects.get(batch_id=self.receipt.batch_id, row_ordinal=7)
        self.url = reverse('wave7_editorial_review')

    def test_real_services_shared_get_and_history_preserve_historical_intake(self):
        historical = list(IntakeItem.objects.filter(batch_id=self.receipt.batch_id).values())
        verify_batch_references(self.receipt.batch_id, synthetic_fixtures_only=True)
        self.assertEqual(historical, list(IntakeItem.objects.filter(batch_id=self.receipt.batch_id).values()))
        transition_review(self.row.pk, operation_id=uuid4(), action='start_review',
            expected_status='UNREVIEWED', reason='E5 synthetic integration', synthetic_fixtures_only=True)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, {'batch': self.receipt.batch_id, 'row': self.row.pk}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        stored = response.context['stored'].row
        self.assertEqual((stored.id, stored.question, stored.review_status), (self.row.pk, f.ORIGINAL_QUESTION, 'IN_REVIEW'))
        self.assertEqual(len(stored.events), 1)
        self.assertEqual(stored.references[0].reference_status, 'VERIFIED')
        self.assertTrue(stored.references[0].citation_text)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))
        self.assertEqual(ReviewEvent.objects.count(), 1)
        self.assertEqual(IntakeReference.objects.filter(reference_status='VERIFIED').count(), 3)
        with override_settings(WAVE7_REVIEW_READ_ENABLED=False), self.assertNumQueries(0):
            self.assertEqual(self.client.get(self.url, HTTP_HOST='localhost').status_code, 404)
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method), self.assertNumQueries(0):
                self.assertEqual(getattr(self.client, method)(self.url, HTTP_HOST='localhost').status_code, 405)

    def test_shared_get_retains_state_and_isolates_repeated_ids_across_batches(self):
        other = import_intake(f.synthetic_payload(), idempotency_key=uuid4().hex, synthetic_fixtures_only=True)
        other_row = IntakeItem.objects.get(batch_id=other.batch_id, row_ordinal=7)
        self.assertEqual(self.row.external_id, other_row.external_id)
        self.assertNotEqual(self.row.pk, other_row.pk)
        params = dict(batch=str(self.receipt.batch_id), q='اصطناعي', page='2', page_size='1', review_status='UNREVIEWED')
        listing = self.client.get(self.url, params, HTTP_HOST='localhost')
        self.assertEqual(listing.status_code, 200)
        detail = self.client.get(listing.context['stored_display_rows'][0]['detail_url'], HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(parse_qs(urlsplit(detail.context['stored_return_url']).query), {k: [v] for k, v in params.items()})
        self.assertEqual(self.client.get(self.url, {'batch': self.receipt.batch_id, 'row': other_row.pk}, HTTP_HOST='localhost').status_code, 404)
        self.assertEqual(self.client.get(self.url + '?page=1&page=2', HTTP_HOST='localhost').status_code, 400)

    def test_actual_e4_shared_routes_and_ssr_context_have_identical_exact_sources(self):
        verify_batch_references(self.receipt.batch_id, synthetic_fixtures_only=True)
        params = dict(batch=str(self.receipt.batch_id), q='سؤال اصطناعي',
                      mode='exact', limit='1', offset='0')
        listed_item = IntakeItem.objects.get(batch_id=self.receipt.batch_id, row_ordinal=3)
        request = RequestFactory().get(self.url, params, HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
        with CaptureQueriesContext(connection) as queries:
            listing = self.client.get(reverse('wave7_api_items'), params, HTTP_HOST='localhost')
            context = reference_views.workflow_read_context(request)
            detail = self.client.get(reverse('wave7_api_item', args=[self.row.pk]),
                {'batch': self.receipt.batch_id}, HTTP_HOST='localhost')
            detail_context = reference_views.workflow_read_context(request, item_id=self.row.pk)
        self.assertEqual((listing.status_code, detail.status_code), (200, 200))
        self.assertEqual(listing['Cache-Control'], 'no-store')
        self.assertEqual(context['workflow_page'].as_dict(),
                         {k: v for k, v in listing.json().items() if k != 'kind'})
        self.assertEqual((listing.json()['total'], listing.json()['items'][0]['id']), (1, str(listed_item.pk)))
        self.assertEqual(context['workflow_query'], params['q'])
        self.assertEqual(parse_qs(context['workflow_return_query']), {k: [v] for k, v in params.items()})
        stored = detail_context['workflow_item']
        self.assertEqual(stored.item.question_original, f.ORIGINAL_QUESTION)
        self.assertEqual(stored.source.text, detail.json()['source']['text'])
        self.assertEqual(stored.references[0].source.text, detail.json()['references'][0]['source']['text'])
        self.assertEqual(stored.references[0].citation_text, detail.json()['references'][0]['citation_text'])
        self.assertTrue(stored.references[0].citation_text)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))

    def test_actual_e4_api_default_off_head_and_invalid_requests_never_query(self):
        paths = [reverse('wave7_api_batches'), reverse('wave7_api_items'),
                 reverse('wave7_api_item', args=[self.row.pk])]
        with override_settings(WAVE7_READS_ENABLED=False), self.assertNumQueries(0):
            for path in paths:
                response = self.client.get(path, HTTP_HOST='localhost')
                self.assertEqual((response.status_code, response.json()['error']), (404, 'not_found'))
                self.assertEqual(self.client.head(path, HTTP_HOST='localhost').content, b'')
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method), self.assertNumQueries(0):
                self.assertEqual(getattr(self.client, method)(paths[1], HTTP_HOST='localhost').status_code, 405)
        with self.assertNumQueries(0):
            invalid = self.client.get(paths[1] + '?mode=unknown', HTTP_HOST='localhost')
            self.assertEqual((invalid.status_code, invalid.json()['error']), (400, 'invalid_query'))
            invalid = self.client.get(paths[1], {'q': f.ORIGINAL_QUESTION}, HTTP_HOST='localhost')
            self.assertEqual((invalid.status_code, invalid.json()['error']), (400, 'invalid_query'))
