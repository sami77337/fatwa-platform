"""Local, opt-in GET/HEAD adapter over the existing guarded Wave7 reader."""

from django.apps import apps
from django.conf import settings
from django.core.exceptions import TooManyFieldsSent
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.intake_workflow import contracts as c
from apps.intake_workflow import guards, review
from apps.reference import services

from .views import _failure, local_only
from .workflow_audit import AuditDataError, build_audit_timeline, serialize_audit_json
from .workflow_audit_query import build_audit_navigation, parse_audit_query


@require_safe
def workflow_audit(request: HttpRequest) -> HttpResponse:
    local_only(request)
    if (getattr(settings, 'WAVE7_READS_ENABLED', False) is not True
            or not apps.is_installed('apps.intake_workflow')
            or not services._workflow_reads_enabled()):
        return _failure('الخط الزمني المحفوظ غير متاح', 404)
    try:
        output_format, reader_parameters = parse_audit_query(request.GET)
        # Domain validation remains in the existing reader, before database access.
        stored = review.load_review_worklist(**reader_parameters, synthetic_fixtures_only=True)
    except (ValueError, TooManyFieldsSent) as exc:
        return _failure('معايير أو سجل غير صالح', getattr(exc, 'status_code', 400))
    except (guards.SyntheticWriteDenied, DatabaseError):
        return _failure('الخط الزمني المحفوظ غير متاح', 503)
    try:
        if output_format == 'json':
            response = HttpResponse(serialize_audit_json(stored), content_type='application/json')
            response['Cache-Control'] = 'no-store'
            return response
        timeline = build_audit_timeline(stored)
    except AuditDataError:
        return _failure('الخط الزمني المحفوظ غير متاح', 503)
    base = reverse('wave7_workflow_audit')
    response = render(request, 'editorial_demo/workflow_audit.html', {
        'stored': stored, 'timeline': timeline,
        **build_audit_navigation(stored, base, reverse('wave7_editorial_review')),
        'intake_statuses': tuple(c.IntakeStatus), 'review_statuses': tuple(c.ReviewStatus),
    })
    response['Cache-Control'] = 'no-store'
    return response
