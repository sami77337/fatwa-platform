"""Read-only audit presentation contracts. No PostgreSQL fixture is provisioned here.

Positive HTTP tests replace only the existing persisted read boundary with its
real immutable DTOs. They are not database integration evidence.
"""

import os
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone, tzinfo
from html import escape
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse

from apps.intake_workflow import contracts as c, fixtures, guards, review


def uid(number):
    return UUID(int=number)


class AuditPageForm(HTMLParser):
    """Read the actual GET controls, including empty and escaped filter values."""

    def __init__(self, html):
        super().__init__()
        self.active = False
        self.attributes = {}
        self.fields = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'audit-page-form':
            self.active = True
            self.attributes = attrs
        elif self.active and tag == 'input' and 'name' in attrs:
            self.fields.append((attrs['name'], attrs.get('value', '')))

    def handle_endtag(self, tag):
        if tag == 'form':
            self.active = False


def synthetic_read():
    """Project existing fabricated source bytes into the existing read contract."""
    parsed = c.parse_synthetic_payload(fixtures.synthetic_payload(), synthetic_fixtures_only=True)
    source, pointer = parsed.item_sources[0], parsed.reference_sources[0][0]
    start = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
    first = review.StoredReviewEvent(uid(31), uid(41), 'start_review', 'UNREVIEWED',
                                    'IN_REVIEW', '  سبب اصطناعي\tأ\n  ', start + timedelta(minutes=1))
    second = review.StoredReviewEvent(uid(32), uid(42), 'request_changes', 'IN_REVIEW',
                                     'NEEDS_CHANGES', 'سبب اصطناعي ثان', start + timedelta(minutes=2))
    reference = review.StoredReference(uid(21), pointer.text, pointer.start, pointer.end,
                                       'VERIFIED', 'استشهاد اصطناعي ثابت')
    row = review.StoredReviewRow(uid(11), uid(1), 1, parsed.items[0]['external_id'],
        parsed.items[0]['question'], source.text, source.start, source.end,
        'READY_FOR_EDITOR', 'NEEDS_CHANGES', parsed.items[0]['prepared_clip_url'],
        (reference,), (second, first))  # Actual reader returns newest first.
    return review.ReviewWorklist((review.ReviewBatchOption(uid(1), start),), uid(1),
        (row,), row, 1, 1, 1, 1, 20, '', 'normalized', '', '')


class AuditProjectionTests(SimpleTestCase):
    def setUp(self):
        from apps.editorial_demo.workflow_audit import AuditDataError, build_audit_timeline
        self.build = build_audit_timeline
        self.error = AuditDataError
        self.stored = synthetic_read()

    def test_chronology_uses_stored_timestamps_and_event_ids(self):
        entries = self.build(self.stored)
        self.assertEqual([entry.kind for entry in entries], ['batch', 'review', 'review'])
        self.assertEqual([entry.source.id for entry in entries], [uid(1), uid(31), uid(32)])
        self.assertIs(entries[0].source, self.stored.batches[0])
        self.assertIs(entries[1].source, self.stored.row.events[1])
        self.assertEqual(entries[2].timestamp, self.stored.row.events[0].created_at.isoformat())

    def test_equal_timestamps_have_stable_uuid_order_and_batch_first(self):
        when = self.stored.batches[0].created_at
        events = tuple(replace(event, created_at=when) for event in self.stored.row.events)
        row = replace(self.stored.row, events=events)
        entries = self.build(replace(self.stored, row=row))
        self.assertEqual([entry.source.id for entry in entries], [uid(1), uid(31), uid(32)])

    def test_repeated_local_hour_orders_instants_without_rewriting_stored_times(self):
        class RepeatedHour(tzinfo):
            def utcoffset(self, value):
                return timedelta(hours=1 - value.fold)

            def dst(self, value):
                return timedelta(0)

        zone = RepeatedHour()
        earlier = replace(self.stored.row.events[1],
            created_at=datetime(2026, 10, 25, 1, 45, tzinfo=zone, fold=0))
        later = replace(self.stored.row.events[0],
            created_at=datetime(2026, 10, 25, 1, 15, tzinfo=zone, fold=1))
        row = replace(self.stored.row, events=(later, earlier))
        entries = self.build(replace(self.stored, row=row))
        self.assertEqual([entry.source.id for entry in entries], [uid(1), uid(31), uid(32)])
        self.assertIs(entries[1].source, earlier)
        self.assertIs(entries[2].source, later)
        self.assertEqual([entry.timestamp for entry in entries[1:]],
            ['2026-10-25T01:45:00+01:00', '2026-10-25T01:15:00+00:00'])

    def test_no_detail_has_no_invented_events(self):
        self.assertEqual(self.build(replace(self.stored, row=None)), ())
        self.assertEqual(self.build(replace(self.stored, batch_id=None, batches=(), rows=(), row=None)), ())

    def test_batch_provenance_remains_when_review_has_not_started(self):
        entries = self.build(replace(self.stored, row=replace(self.stored.row, events=())))
        self.assertEqual(len(entries), 1)
        self.assertIs(entries[0].source, self.stored.batches[0])

    def test_source_unicode_whitespace_reference_order_and_dtos_are_unchanged(self):
        reference = replace(self.stored.row.references[0], id=uid(22),
                            original_pointer='  أ\tأ\n  ', reference_status='UNVERIFIED', citation_text='')
        row = replace(self.stored.row, references=(reference, self.stored.row.references[0]))
        stored = replace(self.stored, row=row)
        before = asdict(stored)
        self.build(stored)
        self.assertEqual(asdict(stored), before)
        self.assertEqual([ref.id for ref in row.references], [uid(22), uid(21)])
        self.assertEqual(row.question, fixtures.ORIGINAL_QUESTION)
        parsed = c.parse_synthetic_payload(fixtures.synthetic_payload(), synthetic_fixtures_only=True)
        self.assertEqual(row.original_row.encode('utf-8'), parsed.raw[row.source_byte_start:row.source_byte_end])

    def test_ambiguous_identity_or_unbounded_event_data_fails_closed(self):
        event = self.stored.row.events[0]
        bad_rows = (
            replace(self.stored.row, batch_id=uid(2)),
            replace(self.stored.row, events=(event, event)),
            replace(self.stored.row, events=(event, replace(event, id=uid(99)))),
            replace(self.stored.row, events=(replace(event, id=str(event.id)),)),
            replace(self.stored.row, events=(replace(event, created_at=datetime(2026, 10, 22)),)),
            replace(self.stored.row, events=(event,) * 101),
        )
        for row in bad_rows:
            with self.subTest(row=row), self.assertRaises(self.error):
                self.build(replace(self.stored, row=row))
        for batches in ((), self.stored.batches * 2):
            with self.assertRaises(self.error):
                self.build(replace(self.stored, batches=batches))


@override_settings(ROOT_URLCONF='config.wave7_urls', WAVE7_READS_ENABLED=True,
                   INSTALLED_APPS=[*settings.INSTALLED_APPS, 'apps.intake_workflow'])
class AuditPageTests(SimpleTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, FATWA_PRODUCTION='0', FATWA_WAVE7_SYNTHETIC_READS='1')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.stored = synthetic_read()
        self.url = '/dev/editorial-preview/workflow-audit'

    def get(self, params=None, stored=None, method='get', **extra):
        with patch.object(review, 'load_review_worklist', return_value=stored or self.stored) as reader:
            response = getattr(self.client, method)(self.url, params or {},
                HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1', **extra)
        return response, reader

    def test_wave7_route_and_get_head_are_read_only_and_uncached(self):
        self.assertEqual(resolve(self.url).url_name, 'wave7_workflow_audit')
        response, reader = self.get({'batch': str(uid(1)), 'row': str(uid(11))})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        reader.assert_called_once_with(batch_id=str(uid(1)), row_id=str(uid(11)), q='',
            mode='normalized', intake_status='', review_status='', page=1, page_size=20,
            synthetic_fixtures_only=True)
        head, _ = self.get(method='head')
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')
        self.assertEqual(head['Cache-Control'], 'no-store')

    def test_provenance_event_identity_and_separate_history_are_explicit(self):
        response, _ = self.get()
        self.assertContains(response, 'lang="ar" dir="rtl"')
        self.assertContains(response, 'إنشاء الدفعة المحفوظة')
        self.assertContains(response, 'ليس وقت استلام مستقلًا للسجل')
        self.assertContains(response, 'لا يحتوي حدث تغيير الحالة على لقطة نصية')
        self.assertContains(response, 'سجل المراجعات التحريرية الثابتة منفصل')
        for identity in (uid(1), uid(11), uid(21), uid(31), uid(32), uid(41), uid(42)):
            self.assertContains(response, str(identity))
        self.assertContains(response, 'W7-SOURCE')
        self.assertContains(response, 'W7-HEADING-1')
        self.assertContains(response, 'start_review')
        self.assertContains(response, 'request_changes')
        self.assertContains(response, 'NEEDS_CHANGES')
        self.assertEqual([entry.source.id for entry in response.context['timeline']],
                         [uid(1), uid(31), uid(32)])

    def test_references_are_current_state_not_invented_verification_events(self):
        row = self.stored.row
        second = replace(row.references[0], id=uid(22), original_pointer='  مؤشر ثان\t\n ',
                         reference_status='MISMATCHED', citation_text='')
        stored = replace(self.stored, row=replace(row, references=(second, *row.references)))
        response, _ = self.get(stored=stored)
        self.assertEqual(response.context['stored'].row.references[0], second)
        self.assertLess(response.content.index(str(uid(22)).encode()), response.content.index(str(uid(21)).encode()))
        self.assertContains(response, 'لا يوفّر عقد القراءة وقت تحقق المرجع أو تاريخ تغيّراته')
        self.assertContains(response, 'استشهاد اصطناعي ثابت')
        self.assertContains(response, 'MISMATCHED')
        self.assertEqual(len(response.context['timeline']), 3)

    def test_html_is_escaped_and_source_whitespace_is_not_stripped(self):
        attack = '\n  أ\tأ <script>alert("x")</script><img src=x onerror=alert(1)>  '
        row = self.stored.row
        reference = replace(row.references[0], original_pointer=attack, citation_text=attack)
        event = replace(row.events[0], reason=attack)
        row = replace(row, external_id=attack, question=attack, original_row=attack,
                      prepared_clip_url=attack, references=(reference,), events=(event,))
        response, _ = self.get(stored=replace(self.stored, row=row))
        body = response.content.decode()
        self.assertNotIn('<script', body)
        self.assertNotIn('<img', body)
        self.assertIn(escape(attack, quote=True), body)
        self.assertIn('<span>' + escape(attack, quote=True) + '</span>', body)
        self.assertEqual(response.context['stored'].row.question, attack)

    def test_event_window_is_disclosed_without_claiming_complete_history(self):
        stored = replace(self.stored, row=replace(self.stored.row, events_truncated=True))
        response, _ = self.get(stored=stored)
        self.assertContains(response, 'آخر 100 حدث فقط')
        self.assertContains(response, 'الأحداث الأقدم غير معروضة هنا')

    def test_filtered_list_navigation_keeps_uuid_state_and_pagination_bounded(self):
        stored = replace(self.stored, row=None, q='أ أ', mode='literal', intake_status='READY_FOR_EDITOR',
                         review_status='NEEDS_CHANGES', page=2, page_count=3, page_size=1,
                         matched_count=3, total_count=4)
        response, _ = self.get(stored=stored)
        expected = dict(batch=[str(uid(1))], q=['أ أ'], mode=['literal'],
            intake_status=['READY_FOR_EDITOR'], review_status=['NEEDS_CHANGES'], page=['2'], page_size=['1'])
        detail = parse_qs(urlsplit(response.context['display_rows'][0]['detail_url']).query)
        self.assertEqual(detail, {**expected, 'row': [str(uid(11))]})
        self.assertEqual(parse_qs(urlsplit(response.context['previous_url']).query), {**expected, 'page': ['1']})
        self.assertEqual(parse_qs(urlsplit(response.context['next_url']).query), {**expected, 'page': ['3']})
        self.assertNotIn('row', parse_qs(urlsplit(response.context['list_url']).query))
        self.assertContains(response, 'method="get"')
        self.assertContains(response, 'max="50"')

    def test_detail_return_links_preserve_filters_and_event_anchors(self):
        response, _ = self.get()
        selected = parse_qs(urlsplit(response.context['selected_url']).query)
        self.assertEqual(selected['row'], [str(uid(11))])
        self.assertNotIn('row', parse_qs(urlsplit(response.context['list_url']).query))
        self.assertContains(response, '#event-' + str(uid(31)))
        self.assertContains(response, 'id="event-' + str(uid(31)) + '" tabindex="-1"')
        self.assertContains(response, 'href="#main-content"')
        self.assertContains(response, '<label for="audit-batch">')
        self.assertNotContains(response, 'method="post"')

    def test_first_last_pages_preserve_filters_and_focus_the_results(self):
        stored = replace(self.stored, row=None, q='أ أ', mode='literal',
            intake_status='READY_FOR_EDITOR', review_status='NEEDS_CHANGES',
            page=2, page_count=3, page_size=1, matched_count=3, total_count=4)
        response, _ = self.get(stored=stored)
        expected = dict(batch=[str(uid(1))], q=['أ أ'], mode=['literal'],
            intake_status=['READY_FOR_EDITOR'], review_status=['NEEDS_CHANGES'],
            page_size=['1'])
        for name, page in (('first_url', '1'), ('previous_url', '1'),
                           ('next_url', '3'), ('last_url', '3')):
            with self.subTest(name=name):
                url = urlsplit(response.context[name])
                self.assertEqual(url.path, self.url)
                self.assertEqual(url.fragment, 'records')
                self.assertEqual(parse_qs(url.query), {**expected, 'page': [page]})
                self.assertContains(response, escape(response.context[name], quote=True))
        self.assertContains(response, 'aria-describedby="audit-pagination-summary"')
        self.assertContains(response, 'id="records" tabindex="-1"')

    def test_pagination_edges_and_empty_results_do_not_offer_missing_pages(self):
        cases = ((1, 3, False, True), (3, 3, True, False), (1, 1, False, False))
        for page, page_count, has_previous, has_next in cases:
            stored = replace(self.stored, row=None, page=page, page_count=page_count,
                page_size=1, matched_count=page_count, total_count=page_count)
            with self.subTest(page=page, page_count=page_count):
                response, _ = self.get(stored=stored)
                for key in ('first_url', 'previous_url'):
                    self.assertEqual(response.context[key] is not None, has_previous)
                for key in ('last_url', 'next_url'):
                    self.assertEqual(response.context[key] is not None, has_next)
                form = AuditPageForm(response.content.decode())
                self.assertEqual(dict(form.fields)['page'], str(page))
                self.assertContains(response, 'id="audit-page" name="page" type="number" min="1" max="'
                    + str(page_count) + '"')
        empty = replace(self.stored, row=None, rows=(), matched_count=0, total_count=0)
        response, _ = self.get(stored=empty)
        self.assertEqual(AuditPageForm(response.content.decode()).fields, [])
        self.assertNotContains(response, 'aria-current="page"')

    def test_page_form_round_trip_keeps_filter_bytes_and_drops_selected_row(self):
        query = '  أ + &= "  '
        listed = replace(self.stored, row=None, q=query, mode='exact',
            review_status='NEEDS_CHANGES', page=2, page_count=3,
            page_size=1, matched_count=3, total_count=4)
        # Controls come from the returned DTO, rather than stale request values.
        response, _ = self.get({'q': 'stale', 'mode': 'literal'}, stored=listed)
        form = AuditPageForm(response.content.decode())
        self.assertEqual(form.attributes['method'], 'get')
        self.assertEqual(form.attributes['action'], self.url + '#records')
        self.assertEqual(len({name for name, _ in form.fields}), len(form.fields))
        params = dict(form.fields)
        self.assertEqual(params, dict(batch=str(uid(1)), q=query, mode='exact',
            intake_status='', review_status='NEEDS_CHANGES', page='2', page_size='1'))
        params['page'] = '3'
        response, reader = self.get(params, stored=replace(listed, page=3))
        self.assertEqual(response.status_code, 200)
        reader.assert_called_once_with(batch_id=str(uid(1)), row_id=None, q=query,
            mode='exact', intake_status='', review_status='NEEDS_CHANGES', page=3,
            page_size=1, synthetic_fixtures_only=True)
        detail, _ = self.get(stored=replace(listed, row=self.stored.row))
        self.assertEqual(urlsplit(detail.context['list_url']).fragment, 'records')
        self.assertNotIn('row', parse_qs(urlsplit(detail.context['list_url']).query))

    def test_selected_record_outside_filtered_page_is_disclosed(self):
        response, _ = self.get(stored=replace(self.stored, rows=(), q='لا يطابق', matched_count=0))
        self.assertContains(response, 'السجل المحدد غير موجود في الصفحة الحالية من القائمة المصفاة')
        self.assertContains(response, 'الرابط الثابت لا يعني مطابقته للتصفية')
        response, _ = self.get()
        self.assertNotContains(response, 'السجل المحدد غير موجود في الصفحة الحالية')

    def test_event_navigation_names_actual_actions_and_stored_times(self):
        response, _ = self.get()
        self.assertContains(response, '<article aria-labelledby="event-'
            + str(uid(31)) + '-heading">')
        self.assertContains(response, 'id="event-' + str(uid(31)) + '-heading"')
        for event in self.stored.row.events:
            self.assertContains(response, 'حدث ' + str(event.id) + ' — '
                + event.action + ' — ' + event.created_at.isoformat())

    def test_empty_batches_and_no_review_events_have_no_fake_timeline(self):
        empty = replace(self.stored, batches=(), batch_id=None, rows=(), row=None,
                        total_count=0, matched_count=0)
        response, _ = self.get(stored=empty)
        self.assertEqual(response.context['timeline'], ())
        self.assertContains(response, 'لا توجد دفعات اصطناعية متاحة')
        no_events = replace(self.stored, row=replace(self.stored.row, events=()))
        response, _ = self.get(stored=no_events)
        self.assertContains(response, 'لا توجد أحداث مراجعة محفوظة لهذا السجل')

    def test_persisted_editorial_page_links_to_same_selected_record(self):
        with patch.object(review, 'load_review_worklist', return_value=self.stored):
            response = self.client.get(reverse('wave7_editorial_review'),
                HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url + '?')
        query = parse_qs(response.context['stored_audit_query'])
        self.assertEqual(query['row'], [str(uid(11))])
        self.assertEqual(query['batch'], [str(uid(1))])

    def test_unsupported_methods_never_call_reader(self):
        for method in ('post', 'put', 'patch', 'delete', 'options', 'trace'):
            with self.subTest(method=method):
                response, reader = self.get(method=method)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response['Allow'], 'GET, HEAD')
                reader.assert_not_called()

    def test_unknown_duplicate_or_malformed_query_rejected_before_database(self):
        queries = ['other=1', 'page=1&page=2', 'batch=a&batch=b', 'row=1', 'batch=',
            'batch=' + str(uid(1)).replace('-', ''), 'batch=' + str(UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')).upper(),
            'batch=' + str(uid(1)) + '&row=bogus', 'q=' + 'a' * 81, 'q=a%00b',
            'mode=invalid', 'intake_status=INVALID', 'review_status=INVALID',
            'page=0', 'page=01', 'page=-1', 'page=١', 'page=10001', 'page_size=0',
            'page_size=51', 'page=10000&page_size=50', 'q=' + urlencode({'x': 'a ' * 11})[2:]]
        for query in queries:
            with self.subTest(query=query), patch.object(review, '_workflow_read') as database_boundary:
                response = self.client.get(self.url + '?' + query,
                    HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response['Cache-Control'], 'no-store')
                database_boundary.assert_not_called()

    def test_unknown_record_and_unavailable_store_are_safe_errors(self):
        for error, status in ((review.ReviewNotFound('private detail'), 404),
                              (review.ReviewUnavailable('private detail'), 503),
                              (guards.SyntheticWriteDenied('private detail'), 503),
                              (DatabaseError('private detail'), 503)):
            with self.subTest(error=error), patch.object(review, 'load_review_worklist', side_effect=error):
                response = self.client.get(self.url, HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
                self.assertEqual(response.status_code, status)
                self.assertNotContains(response, 'private detail', status_code=status)
                self.assertEqual(response['Cache-Control'], 'no-store')

    def test_inconsistent_read_contract_returns_503(self):
        response, _ = self.get(stored=replace(self.stored, batches=()))
        self.assertEqual(response.status_code, 503)

    def test_feature_flags_and_installed_app_are_required(self):
        with self.settings(WAVE7_READS_ENABLED=False):
            response, reader = self.get()
            self.assertEqual(response.status_code, 404)
            reader.assert_not_called()
        with patch.dict(os.environ, FATWA_WAVE7_SYNTHETIC_READS='0'):
            response, reader = self.get()
            self.assertEqual(response.status_code, 404)
            reader.assert_not_called()
        with self.settings(INSTALLED_APPS=[app for app in settings.INSTALLED_APPS if app != 'apps.intake_workflow']):
            response, reader = self.get()
            self.assertEqual(response.status_code, 404)
            reader.assert_not_called()

    def test_loopback_and_production_guards_deny_before_reader(self):
        for host, peer in (('testserver', '127.0.0.1'), ('localhost', '192.0.2.1'),
                           ('localhost', ''), ('localhost', 'bad-address')):
            with self.subTest(host=host, peer=peer), patch.object(review, 'load_review_worklist') as reader:
                response = self.client.get(self.url, HTTP_HOST=host, REMOTE_ADDR=peer)
                self.assertEqual(response.status_code, 404)
                reader.assert_not_called()
        for overrides in ({'FATWA_PRODUCTION': True}, {'SETTINGS_MODULE': 'config.settings.production'}):
            with self.settings(**overrides):
                response, reader = self.get()
                self.assertEqual(response.status_code, 404)
                reader.assert_not_called()
        with patch.dict(os.environ, FATWA_PRODUCTION='1'):
            response, reader = self.get()
            self.assertEqual(response.status_code, 404)
            reader.assert_not_called()

    def test_ipv6_loopback_is_allowed(self):
        with patch.object(review, 'load_review_worklist', return_value=self.stored):
            response = self.client.get(self.url, HTTP_HOST='[::1]', REMOTE_ADDR='::1')
        self.assertEqual(response.status_code, 200)

    @override_settings(ROOT_URLCONF='config.urls')
    def test_default_profile_does_not_register_audit_route(self):
        response, reader = self.get()
        self.assertEqual(response.status_code, 404)
        reader.assert_not_called()
