"""Focused query/navigation contracts; synthetic DTOs, no database integration."""

import os
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from django.conf import settings
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings

from apps.intake_workflow import review
from tests.editorial_demo.test_workflow_audit import synthetic_read, uid


class AuditQueryHelperTests(SimpleTestCase):
    def parse(self, raw):
        from apps.editorial_demo.workflow_audit_query import parse_audit_query
        return parse_audit_query(QueryDict(raw))

    def test_request_order_does_not_change_reader_parameters_or_filter_bytes(self):
        first = self.parse('format=json&page_size=1&page=2&q=++%D8%A7%D9%94+%2B+%26%3D+%22++&mode=exact')
        second = self.parse('mode=exact&q=++%D8%A7%D9%94+%2B+%26%3D+%22++&page=2&page_size=1&format=json')
        self.assertEqual(first, second)
        self.assertEqual(first, ('json', {
            'batch_id': None, 'row_id': None, 'q': '  أ + &= "  ', 'mode': 'exact',
            'intake_status': '', 'review_status': '', 'page': 2, 'page_size': 1,
        }))
        self.assertEqual(self.parse(''), ('html', {
            'batch_id': None, 'row_id': None, 'q': '', 'mode': 'normalized',
            'intake_status': '', 'review_status': '', 'page': 1, 'page_size': 20,
        }))

    def test_ambiguous_query_and_noncanonical_integers_fail_without_coercion(self):
        for raw in ('x=1', 'q=a&q=a', 'format=json&format=json', 'format=', 'format=JSON',
                    'page=', 'page=01', 'page=+1', 'page=١', 'page=-1', 'page=1.0',
                    'page=10001', 'page=' + '9' * 10000, 'page_size=0', 'page_size=51'):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                self.parse(raw)
        self.assertEqual(self.parse('page=10000&page_size=50')[1]['page'], 10000)
        # Combined offset bounds remain the reader's responsibility.

    def test_domain_parameters_are_passed_unchanged_to_the_existing_reader(self):
        raw = 'batch=&row=bad&mode=bad&intake_status=bad&review_status=bad&q=a%00b'
        self.assertEqual(self.parse(raw)[1], {
            'batch_id': '', 'row_id': 'bad', 'q': 'a\x00b', 'mode': 'bad',
            'intake_status': 'bad', 'review_status': 'bad', 'page': 1, 'page_size': 20,
        })

    def test_navigation_uses_dto_filters_and_preserves_selected_identity_off_page(self):
        from apps.editorial_demo.workflow_audit_query import build_audit_navigation
        stored = replace(synthetic_read(), rows=(), q='  أ + &= "  ', mode='exact',
                         intake_status='READY_FOR_EDITOR', review_status='NEEDS_CHANGES',
                         page=2, page_count=3, page_size=1)
        navigation = build_audit_navigation(stored, '/audit', '/review')
        expected = [('q', '  أ + &= "  '), ('mode', 'exact'),
                    ('intake_status', 'READY_FOR_EDITOR'), ('review_status', 'NEEDS_CHANGES'),
                    ('page', '2'), ('page_size', '1'), ('batch', str(uid(1)))]
        self.assertFalse(navigation['selected_on_page'])
        self.assertEqual(navigation['display_rows'], ())
        for name, path, selected, fragment in (
                ('list_url', '/audit', False, 'records'),
                ('selected_url', '/audit', True, ''), ('persisted_url', '/review', True, '')):
            with self.subTest(name=name):
                link = urlsplit(navigation[name])
                self.assertEqual((link.path, link.fragment), (path, fragment))
                self.assertEqual(parse_qsl(link.query, keep_blank_values=True),
                                 expected + ([('row', str(uid(11)))] if selected else []))
        self.assertEqual(navigation['pagination_fields'],
                         tuple((key, value) for key, value in [
                             ('q', stored.q), ('mode', 'exact'), ('intake_status', 'READY_FOR_EDITOR'),
                             ('review_status', 'NEEDS_CHANGES'), ('page_size', 1), ('batch', str(uid(1)))]))
        for name, page in (('first_url', '1'), ('previous_url', '1'), ('next_url', '3'), ('last_url', '3')):
            link = urlsplit(navigation[name])
            self.assertEqual(link.fragment, 'records')
            self.assertEqual(dict(parse_qsl(link.query, keep_blank_values=True)), {**dict(expected), 'page': page})
        self.assertEqual(stored.q, '  أ + &= "  ')

    def test_navigation_edges_unselected_and_empty_state_have_no_spurious_ids(self):
        from apps.editorial_demo.workflow_audit_query import build_audit_navigation
        source = synthetic_read()
        for page, count, previous, following in ((1, 3, False, True), (3, 3, True, False), (1, 1, False, False)):
            with self.subTest(page=page, count=count):
                nav = build_audit_navigation(replace(source, row=None, page=page, page_count=count), '/audit', '/review')
                self.assertEqual(nav['first_url'] is not None, previous)
                self.assertEqual(nav['previous_url'] is not None, previous)
                self.assertEqual(nav['next_url'] is not None, following)
                self.assertEqual(nav['last_url'] is not None, following)
                self.assertNotIn('row', dict(parse_qsl(urlsplit(nav['selected_url']).query)))
                self.assertEqual(dict(parse_qsl(urlsplit(nav['display_rows'][0]['detail_url']).query))['row'], str(uid(11)))
                self.assertFalse(nav['selected_on_page'])
        nav = build_audit_navigation(source, '/audit', '/review')
        self.assertTrue(nav['selected_on_page'])
        empty = replace(source, batch_id=None, row=None, rows=(), batches=(), matched_count=0)
        nav = build_audit_navigation(empty, '/audit', '/review')
        self.assertNotIn('batch', dict(nav['pagination_fields']))
        self.assertNotIn('row', dict(parse_qsl(urlsplit(nav['selected_url']).query)))


@override_settings(ROOT_URLCONF='config.wave7_urls', WAVE7_READS_ENABLED=True,
                   INSTALLED_APPS=[*settings.INSTALLED_APPS, 'apps.intake_workflow'])
class AuditQueryAdapterTests(SimpleTestCase):
    def setUp(self):
        env = patch.dict(os.environ, FATWA_PRODUCTION='0', FATWA_WAVE7_SYNTHETIC_READS='1')
        env.start()
        self.addCleanup(env.stop)
        self.url = '/dev/editorial-preview/workflow-audit'

    def test_invalid_http_parameters_never_enter_reader(self):
        for raw in ('row=a&row=a', 'x=1', 'page=01', 'page_size=51', 'format=JSON'):
            with self.subTest(raw=raw), patch.object(review, 'load_review_worklist', side_effect=AssertionError('reader entered')):
                response = self.client.get(self.url + '?' + raw, HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response['Cache-Control'], 'no-store')

    def test_domain_rejections_still_precede_database_boundary(self):
        for raw in ('row=bogus', 'q=' + 'a' * 81, 'mode=invalid', 'page=10000&page_size=50'):
            with self.subTest(raw=raw), patch.object(review, '_workflow_read', side_effect=AssertionError('database entered')):
                response = self.client.get(self.url + '?' + raw, HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response['Cache-Control'], 'no-store')

    def test_rendered_navigation_uses_reader_state_instead_of_request_order(self):
        stored = replace(synthetic_read(), page=2, page_count=3, page_size=1, q='أ + &= "', mode='literal')
        with patch.object(review, 'load_review_worklist', return_value=stored):
            first = self.client.get(self.url + '?page=2&q=stale', HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
            second = self.client.get(self.url + '?q=stale&page=2', HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.context['selected_url'], second.context['selected_url'])
        values = dict(parse_qsl(urlsplit(first.context['selected_url']).query, keep_blank_values=True))
        self.assertEqual(values['q'], 'أ + &= "')
        self.assertEqual(values['row'], str(uid(11)))
        self.assertEqual(urlsplit(first.context['next_url']).fragment, 'records')
        self.assertContains(first, '#event-' + str(uid(31)))
        self.assertEqual(first['Cache-Control'], 'no-store')
