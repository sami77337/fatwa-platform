"""Opt-in loopback training report, not a public or production API."""
import os
from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from apps.editorial_workbench.reviewer_access import signed_in, set_role_cookie
from apps.editorial_workbench.source_review_identity import authenticate_fixture_role
from .reporting import export_scoped_report
from .services import QueueConflict

CSS = '''body{font:18px/1.7 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#17202a}main,header,nav{max-width:960px;margin:auto;padding:1rem;box-sizing:border-box}article{background:white;border:1px solid #cbd2d9;padding:1rem;margin:1rem 0;border-radius:.5rem;overflow-wrap:anywhere}h1{font-size:1.7rem}h2{font-size:1.25rem}a{color:#064c92}a:focus,button:focus,input:focus{outline:3px solid #705b00;outline-offset:3px}input,button{font:inherit;max-width:100%;box-sizing:border-box;padding:.5rem}label{display:block}dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:.5rem}dt,dd{margin:0;overflow-wrap:anywhere}.skip{display:inline-block;margin:.6rem}.note{border-right:4px solid #705b00;padding:.5rem}li{overflow-wrap:anywhere}@media(max-width:480px){main,header,nav{padding:.7rem}dl{display:block}dd{margin-bottom:.6rem}}'''


def _private(response, *, head=False):
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Vary'] = 'Cookie'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Referrer-Policy'] = 'same-origin'
    response['Content-Security-Policy'] = "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    if head:
        response.content = b''
    return response


def _enabled():
    return os.environ.get('FATWA_PRODUCTION') == '0' and getattr(settings, 'FATWA_PG_DELIVERY_REPORTS_ENABLED', False) is True


def _deny(code, status):
    return _private(JsonResponse({'error': code}, status=status))


def _read_report(request, *, as_json):
    if request.method not in ('GET', 'HEAD'):
        response = _deny('read_only_endpoint', 405)
        response['Allow'] = 'GET, HEAD'
        return response
    if not _enabled():
        return _deny('training_report_disabled', 503)
    if not signed_in(request, 'operator'):
        return _deny('operator_authentication_required', 403)
    if set(request.GET) - {'after'} or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        return _deny('invalid_report_query', 400)
    scopes = getattr(settings, 'FATWA_PG_DELIVERY_OPERATOR_CASES', {})
    assigned = scopes.get('synthetic-operator', ()) if type(scopes) is dict else ()
    if type(assigned) not in (tuple, list) or not assigned:
        return _deny('operator_scope_not_configured', 403)
    try:
        report = export_scoped_report(case_keys=frozenset(assigned), after=request.GET.get('after'))
    except QueueConflict:
        return _deny('report_unavailable_or_invalid', 503)
    except DatabaseError:
        return _deny('report_store_unavailable', 503)
    if as_json:
        response = JsonResponse(report, json_dumps_params={'ensure_ascii': False})
        response['Content-Disposition'] = 'attachment; filename="delivery-report.json"'
    else:
        response = render(request, 'delivery_queue/report.html', {'report': report})
    return _private(response, head=request.method == 'HEAD')


def report_json(request):
    return _read_report(request, as_json=True)


def report_page(request):
    return _read_report(request, as_json=False)


def stylesheet(request):
    if request.method not in ('GET', 'HEAD'):
        return _deny('read_only_endpoint', 405)
    return _private(HttpResponse(CSS, content_type='text/css; charset=utf-8'), head=request.method == 'HEAD')


@sensitive_post_parameters('token')
@csrf_protect
def operator_login(request):
    if not _enabled():
        return _deny('training_report_disabled', 503)
    if request.method not in ('GET', 'HEAD', 'POST'):
        return _deny('unsupported_login_method', 405)
    if request.GET:
        return _deny('invalid_login_query', 400)
    message = ''
    if request.method == 'POST':
        if set(request.POST) - {'csrfmiddlewaretoken', 'token'} or len(request.POST.getlist('token')) != 1:
            return _deny('invalid_login_form', 400)
        try:
            authenticate_fixture_role(request.POST.get('token'), 'operator')
        except ValueError:
            message = 'تعذر التحقق من رمز المشغّل.'
        else:
            rotate_token(request)
            response = HttpResponse(status=303)
            response['Location'] = '/review/operator/postgres/'
            return _private(set_role_cookie(request, response, 'operator'))
    get_token(request)
    return _private(render(request, 'delivery_queue/login.html', {'message': message}), head=request.method == 'HEAD')


class LoopbackReviewGuard:
    """Reject non-loopback access and report mutations before CSRF middleware."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get('REMOTE_ADDR') not in ('127.0.0.1', '::1') or not _enabled():
            return _deny('loopback_training_only', 403)
        allowed = {'/review/operator/login/', '/review/operator/postgres/',
                   '/review/operator/postgres.json', '/review/operator/queue.css'}
        if request.path not in allowed:
            return _deny('not_found', 404)
        if request.method not in ('GET', 'HEAD') and not (request.path == '/review/operator/login/' and request.method == 'POST'):
            return _deny('read_only_endpoint', 405)
        return _private(self.get_response(request), head=request.method == 'HEAD')
