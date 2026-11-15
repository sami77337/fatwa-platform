"""Default-off local author handoff. Authors import approval; they never sign it."""
from hmac import compare_digest
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.delivery_planner.segmentation import SegmentationNeedsReview
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier
from apps.editorial_workbench.reviewer_access import signed_in, set_role_cookie, browser_proof
from apps.editorial_workbench.source_review_identity import authenticate_fixture_role
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from apps.fast9_case_source_join.return_handoff import read_return_candidate
from apps.fast9_case_source_join.source_journal import JournalError
from .author_handoff import build_approval_request, stage_signed_response, HandoffBlocked, InvalidSignedResponse

BASE = '/review/author/approval/'
PURPOSE = 'training.author-approval-staging.v1'
CSS = '''body{font:18px/1.7 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#17202a}main,header{max-width:960px;margin:auto;padding:1rem;box-sizing:border-box}article,form{background:white;border:1px solid #cbd2d9;padding:1rem;margin:1rem 0;border-radius:.5rem;overflow-wrap:anywhere}h1{font-size:1.7rem}h2{font-size:1.25rem}a{color:#064c92}a:focus,button:focus,input:focus,textarea:focus{outline:3px solid #705b00;outline-offset:3px}input,button,textarea{font:inherit;max-width:100%;box-sizing:border-box;padding:.5rem}input[type=checkbox]{width:auto}textarea{width:100%;min-height:10rem;direction:ltr}label{display:block}pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere;tab-size:4}.skip{display:inline-block;margin:.6rem}.note{border-right:4px solid #705b00;padding:.5rem}code,bdi{overflow-wrap:anywhere}button{cursor:pointer}@media(max-width:480px){main,header{padding:.7rem}form,article{padding:.65rem}}'''


def _private(response, *, head=False):
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Vary'] = 'Cookie'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Referrer-Policy'] = 'same-origin'
    response['Content-Security-Policy'] = "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    if head:
        response.content = b''
    return response


def _deny(code, status):
    return _private(JsonResponse({'error': code}, status=status))


def _enabled():
    return os.environ.get('FATWA_PRODUCTION') == '0' and getattr(settings, 'FATWA_AUTHOR_APPROVAL_ENABLED', False) is True


def _author(request):
    if not _enabled():
        return _deny('author_approval_disabled', 503)
    if not signed_in(request, 'author'):
        return _deny('author_authentication_required', 403)
    cases = getattr(settings, 'FATWA_AUTHOR_APPROVAL_CASES', ())
    if type(cases) not in (tuple, list) or CASE_KEY not in cases:
        return _deny('author_case_not_assigned', 403)
    return None


def _configuration():
    directory = getattr(settings, 'FATWA_AUTHOR_APPROVAL_DIRECTORY', None)
    max_chars = getattr(settings, 'FATWA_AUTHOR_APPROVAL_MAX_CHARS', 280)
    if (not isinstance(directory, (str, Path)) or not str(directory)
        or type(max_chars) is not int or not 1 <= max_chars <= 6000):
        raise OSError('author_desk_configuration_missing')
    directory = Path(directory)
    if not directory.is_dir():
        raise OSError('author_journal_directory_unavailable')
    return directory, max_chars


def _split_query(request):
    if (set(request.GET) - {'split'} or any(len(request.GET.getlist(key)) != 1 for key in request.GET)
        or ('split' in request.GET and request.GET['split'] != '1')):
        raise InvalidSignedResponse('invalid_preview_options')
    return 'split' in request.GET


def _package(directory, maximum, split):
    return build_approval_request(directory, case_key=CASE_KEY, max_chars=maximum,
        split=split, synthetic_fixtures_only=True)


def author_page(request):
    denied = _author(request)
    if denied is not None:
        return denied
    if request.method not in ('GET', 'HEAD'):
        return _deny('read_only_preview', 405)
    try:
        split = _split_query(request)
        directory, maximum = _configuration()
        candidate = read_return_candidate(directory, synthetic_fixtures_only=True)
        context = {'candidate': candidate, 'split': split, 'maximum': maximum,
            'body': candidate.draft.body if candidate.draft else '',
            'title': candidate.draft.title if candidate.draft else '',
            'verifier_ready': isinstance(getattr(settings, 'FATWA_AUTHOR_APPROVAL_VERIFIER', None), Ed25519ApprovalVerifier)}
        try:
            package = _package(directory, maximum, split)
        except (HandoffBlocked, SegmentationNeedsReview):
            context['blocked'] = True
        else:
            context['package'] = package
            context['confirmation'] = browser_proof(request, PURPOSE, package['request_sha256'])
        get_token(request)
        return _private(render(request, 'delivery_queue/author_approval.html', context), head=request.method == 'HEAD')
    except InvalidSignedResponse:
        return _deny('invalid_preview_options', 400)
    except (OSError, JournalError, ValueError):
        return _deny('author_journal_unavailable', 503)


def export_request(request):
    denied = _author(request)
    if denied is not None:
        return denied
    if request.method not in ('GET', 'HEAD'):
        return _deny('read_only_export', 405)
    try:
        split = _split_query(request)
        directory, maximum = _configuration()
        package = _package(directory, maximum, split)
    except InvalidSignedResponse:
        return _deny('invalid_preview_options', 400)
    except (HandoffBlocked, SegmentationNeedsReview):
        return _deny('current_request_not_ready', 409)
    except (OSError, JournalError, ValueError):
        return _deny('author_journal_unavailable', 503)
    response = JsonResponse(package, json_dumps_params={'ensure_ascii': False})
    response['Content-Disposition'] = 'attachment; filename="approval-request.json"'
    return _private(response, head=request.method == 'HEAD')


@sensitive_post_parameters('response')
@csrf_protect
def import_response(request):
    denied = _author(request)
    if denied is not None:
        return denied
    if request.method != 'POST':
        return _deny('explicit_post_required', 405)
    if request.GET or request.content_type != 'application/x-www-form-urlencoded':
        return _deny('invalid_receipt_form', 400)
    try:
        fields = request.POST
        expected = {'csrfmiddlewaretoken', 'request_sha256', 'confirmation', 'split', 'acknowledge', 'response'}
        if (set(fields) != expected or any(len(fields.getlist(key)) != 1 for key in fields)
            or fields['split'] not in ('0', '1') or fields['acknowledge'] != '1'
            or len(fields['request_sha256']) != 64 or len(fields['confirmation']) != 64):
            return _deny('invalid_receipt_form', 400)
        verifier = getattr(settings, 'FATWA_AUTHOR_APPROVAL_VERIFIER', None)
        if not isinstance(verifier, Ed25519ApprovalVerifier):
            return _deny('trusted_mufti_verifier_not_configured', 503)
        directory, maximum = _configuration()
        split = fields['split'] == '1'
        package = _package(directory, maximum, split)
        if not compare_digest(package['request_sha256'], fields['request_sha256']):
            return _deny('author_preview_is_stale', 409)
        expected_confirmation = browser_proof(request, PURPOSE, package['request_sha256'])
        if not compare_digest(expected_confirmation, fields['confirmation']):
            return _deny('browser_confirmation_invalid', 403)
        result = stage_signed_response(directory, case_key=CASE_KEY, max_chars=maximum,
            split=split, response_json=fields['response'], verifier=verifier,
            synthetic_fixtures_only=True)
        return _private(render(request, 'delivery_queue/author_staged.html', {'result': result}))
    except (InvalidSignedResponse, SuspiciousOperation):
        return _deny('signed_response_invalid', 400)
    except (HandoffBlocked, SegmentationNeedsReview):
        return _deny('current_request_no_longer_ready', 409)
    except (OSError, JournalError, DatabaseError):
        return _deny('handoff_store_unavailable', 503)
    except ValueError:
        return _deny('signed_approval_not_accepted', 403)


@sensitive_post_parameters('token')
@csrf_protect
def author_login(request):
    if not _enabled():
        return _deny('author_approval_disabled', 503)
    if request.GET or request.method not in ('GET', 'HEAD', 'POST'):
        return _deny('invalid_login_request', 400)
    message, status = '', 200
    if request.method == 'POST':
        if request.content_type != 'application/x-www-form-urlencoded':
            return _deny('invalid_login_form', 400)
        try:
            fields = request.POST
            if set(fields) != {'csrfmiddlewaretoken', 'token'} or any(len(fields.getlist(key)) != 1 for key in fields):
                return _deny('invalid_login_form', 400)
            authenticate_fixture_role(fields['token'], 'author')
        except (ValueError, SuspiciousOperation):
            message, status = 'تعذر التحقق من رمز المؤلف.', 403
        else:
            rotate_token(request)
            response = HttpResponse(status=303, headers={'Location': BASE})
            return _private(set_role_cookie(request, response, 'author'))
    get_token(request)
    return _private(render(request, 'delivery_queue/author_login.html', {'message': message}, status=status), head=request.method == 'HEAD')


def stylesheet(request):
    return _private(HttpResponse(CSS, content_type='text/css; charset=utf-8'), head=request.method == 'HEAD')


class AuthorDeskGuard:
    """Keep all author handoff endpoints private, local and explicitly enabled."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _enabled():
            return _deny('author_approval_disabled', 503)
        if request.META.get('REMOTE_ADDR') not in ('127.0.0.1', '::1'):
            return _deny('loopback_training_only', 403)
        allowed = {BASE: ('GET', 'HEAD'), BASE + 'request.json': ('GET', 'HEAD'),
                   BASE + 'receipt/': ('POST',), BASE + 'login/': ('GET', 'HEAD', 'POST'),
                   BASE + 'desk.css': ('GET', 'HEAD')}
        if request.path not in allowed:
            return _deny('not_found', 404)
        if request.method not in allowed[request.path]:
            response = _deny('method_not_allowed', 405)
            response['Allow'] = ', '.join(allowed[request.path])
            return response
        try:
            length = int(request.META.get('CONTENT_LENGTH') or '0')
        except ValueError:
            return _deny('invalid_content_length', 400)
        if length < 0 or length > 65536:
            return _deny('form_too_large', 413)
        return _private(self.get_response(request), head=request.method == 'HEAD')
