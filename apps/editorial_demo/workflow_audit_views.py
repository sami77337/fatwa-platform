"""Local, opt-in GET/HEAD adapter over the existing guarded Wave7 reader."""

from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.core.exceptions import TooManyFieldsSent
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.intake_workflow import contracts as c, guards, review
from apps.reference import services

from .views import _failure, _positive_query, local_only
from .workflow_audit import AuditDataError, build_audit_timeline


@require_safe
def workflow_audit(request: HttpRequest) -> HttpResponse:
    local_only(request)
    if (getattr(settings, 'WAVE7_READS_ENABLED', False) is not True
            or not apps.is_installed('apps.intake_workflow')
            or not services._workflow_reads_enabled()):
        return _failure('الخط الزمني المحفوظ غير متاح', 404)
    try:
        query = request.GET
        if set(query) - {'batch', 'row', 'q', 'mode', 'intake_status', 'review_status', 'page', 'page_size'} or any(
                len(query.getlist(key)) != 1 for key in query):
            raise c.ContractError('review: invalid_query')
        # Canonical UUIDs, search/status bounds and offset limits belong to the
        # existing reader. They are checked there before any database access.
        stored = review.load_review_worklist(
            batch_id=query.get('batch'), row_id=query.get('row'), q=query.get('q', ''),
            mode=query.get('mode', 'normalized'), intake_status=query.get('intake_status', ''),
            review_status=query.get('review_status', ''),
            page=_positive_query(query.get('page', '1'), 10000),
            page_size=_positive_query(query.get('page_size', '20'), 50),
            synthetic_fixtures_only=True,
        )
    except (ValueError, TooManyFieldsSent) as exc:
        return _failure('معايير أو سجل غير صالح', getattr(exc, 'status_code', 400))
    except (guards.SyntheticWriteDenied, DatabaseError):
        return _failure('الخط الزمني المحفوظ غير متاح', 503)
    try:
        timeline = build_audit_timeline(stored)
    except AuditDataError:
        return _failure('الخط الزمني المحفوظ غير متاح', 503)
    base = reverse('wave7_workflow_audit')
    params = dict(q=stored.q, mode=stored.mode, intake_status=stored.intake_status,
                  review_status=stored.review_status, page=stored.page, page_size=stored.page_size)
    if stored.batch_id is not None:
        params['batch'] = str(stored.batch_id)
    selected_params = {**params, **({'row': str(stored.row.id)} if stored.row is not None else {})}

    def page_url(page: int) -> str:
        return base + '?' + urlencode({**params, 'page': page}) + '#records'

    response = render(request, 'editorial_demo/workflow_audit.html', {
        'stored': stored, 'timeline': timeline, 'base_url': base,
        'list_url': page_url(stored.page),
        'selected_url': base + '?' + urlencode(selected_params),
        'persisted_url': reverse('wave7_editorial_review') + '?' + urlencode(selected_params),
        'selected_on_page': stored.row is not None and any(row.id == stored.row.id for row in stored.rows),
        'display_rows': tuple({'item': row, 'detail_url': base + '?' + urlencode({**params, 'row': str(row.id)})}
                              for row in stored.rows),
        'pagination_fields': tuple((key, value) for key, value in params.items() if key != 'page'),
        'first_url': page_url(1) if stored.page > 1 else None,
        'previous_url': page_url(stored.page - 1) if stored.page > 1 else None,
        'next_url': page_url(stored.page + 1) if stored.page < stored.page_count else None,
        'last_url': page_url(stored.page_count) if stored.page < stored.page_count else None,
        'intake_statuses': tuple(c.IntakeStatus), 'review_statuses': tuple(c.ReviewStatus),
    })
    response['Cache-Control'] = 'no-store'
    return response
