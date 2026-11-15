"""Separate local author/Mufti desk; never signs, sends or grants a role."""
from hmac import compare_digest
import os
import secrets
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from apps.delivery_queue import author_http
from apps.delivery_queue.author_handoff import HandoffBlocked, InvalidSignedResponse
from apps.delivery_planner.segmentation import SegmentationNeedsReview
from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.fast9_case_source_join.answer_drafts import AUTHOR, CASE_KEY
from apps.fast9_case_source_join.source_journal import JournalError
from . import services
from .identity import require_provider, authenticate_identity, validate_identity, IdentityUnavailable
from .browser_identity import current_identity, set_identity_cookie, COOKIE
from .models import ReviewDecision

AUTHOR_BASE = '/review/author/approval/'
MUFTI_BASE = '/review/mufti/decisions/'
MUFTI_LOGIN = '/review/mufti/login/'
AUTHOR_PURPOSE = 'mufti-review.author-request.v1'
DECISION_PURPOSE = 'mufti-review.human-decision.v1'


def _enabled():
    return os.environ.get('FATWA_PRODUCTION') == '0' and getattr(settings, 'FATWA_MUFTI_REVIEW_ENABLED', False) is True


def _private(response, *, head=False):
    return author_http._private(response, head=head)


def _deny(code, status):
    return _private(JsonResponse({'error': code}, status=status))


def _provider():
    value = getattr(settings, 'FATWA_MUFTI_IDENTITY_PROVIDER', None)
    require_provider(value)
    return value


def _actor(request):
    try:
        provider = _provider()
    except IdentityUnavailable:
        return None, None, _deny('trusted_identity_provider_not_configured', 503)
    try:
        return provider, current_identity(request, provider, case_key=CASE_KEY), None
    except IdentityUnavailable:
        return None, None, _deny('current_mufti_identity_required', 403)


def _context(request):
    split = author_http._split_query(request)
    directory, maximum = author_http._configuration()
    history = services.review_history(case_key=CASE_KEY, author_id=AUTHOR, synthetic_fixtures_only=True)
    try:
        package = author_http._package(directory, maximum, split)
    except (HandoffBlocked, SegmentationNeedsReview):
        package = None
    current = next((row for row in history if package and row['request_sha256'] == package['request_sha256']), None)
    return {'split': split, 'maximum': maximum, 'package': package, 'history': history,
        'current': current, 'state': current['state'] if current else 'NOT_SUBMITTED',
        'directory': directory}


def _form(request, expected):
    if request.GET or request.content_type != 'application/x-www-form-urlencoded':
        raise InvalidSignedResponse('invalid_native_form')
    values = request.POST
    if set(values) != expected or any(len(values.getlist(key)) != 1 for key in values):
        raise InvalidSignedResponse('invalid_native_form_fields')
    if (values.get('split') not in ('0', '1') or values.get('acknowledge') != '1'
        or services.HEX64.fullmatch(values.get('request_sha256', '')) is None
        or services.HEX64.fullmatch(values.get('confirmation', '')) is None):
        raise InvalidSignedResponse('invalid_snapshot_confirmation')
    return values


def author_page(request):
    denied = author_http._author(request)
    if denied is not None:
        return denied
    try:
        context = _context(request)
        if context['package']:
            context['confirmation'] = browser_proof(request, AUTHOR_PURPOSE, context['package']['request_sha256'])
        context['verifier_ready'] = isinstance(getattr(settings, 'FATWA_AUTHOR_APPROVAL_VERIFIER', None), Ed25519ApprovalVerifier)
        get_token(request)
        return _private(render(request, 'mufti_review/author.html', context), head=request.method == 'HEAD')
    except InvalidSignedResponse:
        return _deny('invalid_preview_query', 400)
    except (ValueError, OSError, DatabaseError, JournalError):
        return _deny('review_snapshot_unavailable', 503)


@csrf_protect
def author_submit(request):
    denied = author_http._author(request)
    if denied is not None:
        return denied
    try:
        values = _form(request, {'csrfmiddlewaretoken', 'request_sha256', 'confirmation', 'split', 'acknowledge'})
        expected = browser_proof(request, AUTHOR_PURPOSE, values['request_sha256'])
        if not compare_digest(expected, values['confirmation']):
            return _deny('author_browser_confirmation_invalid', 403)
        directory, maximum = author_http._configuration()
        services.submit_request(directory, case_key=CASE_KEY, max_chars=maximum,
            split=values['split'] == '1', author_id=AUTHOR,
            expected_request_sha256=values['request_sha256'], synthetic_fixtures_only=True)
        return _private(HttpResponse(status=303, headers={'Location': AUTHOR_BASE + ('?split=1' if values['split'] == '1' else '')}))
    except (InvalidSignedResponse, SuspiciousOperation):
        return _deny('invalid_review_submission', 400)
    except (HandoffBlocked, SegmentationNeedsReview, services.ReviewConflict):
        return _deny('review_request_no_longer_current', 409)
    except (ValueError, OSError, JournalError, DatabaseError):
        return _deny('review_submission_unavailable', 503)


@sensitive_post_parameters('response')
@csrf_protect
def author_stage(request):
    denied = author_http._author(request)
    if denied is not None:
        return denied
    try:
        values = _form(request, {'csrfmiddlewaretoken', 'request_sha256', 'confirmation', 'split', 'acknowledge', 'response'})
        if not compare_digest(browser_proof(request, AUTHOR_PURPOSE, values['request_sha256']), values['confirmation']):
            return _deny('author_browser_confirmation_invalid', 403)
        provider = _provider()
        verifier = getattr(settings, 'FATWA_AUTHOR_APPROVAL_VERIFIER', None)
        if not isinstance(verifier, Ed25519ApprovalVerifier):
            return _deny('trusted_receipt_verifier_not_configured', 503)
        directory, maximum = author_http._configuration()
        package = author_http._package(directory, maximum, values['split'] == '1')
        if package['request_sha256'] != values['request_sha256']:
            return _deny('author_snapshot_is_stale', 409)
        result = services.stage_reviewed_response(directory, case_key=CASE_KEY, max_chars=maximum,
            split=values['split'] == '1', author_id=AUTHOR, response_json=values['response'],
            provider=provider, verifier=verifier, synthetic_fixtures_only=True)
        return _private(render(request, 'delivery_queue/author_staged.html', {'result': result}))
    except (InvalidSignedResponse, SuspiciousOperation):
        return _deny('signed_response_invalid', 400)
    except IdentityUnavailable:
        return _deny('current_mufti_identity_unavailable', 503)
    except (services.ReviewConflict, HandoffBlocked, SegmentationNeedsReview):
        return _deny('matching_current_human_decision_required', 409)
    except (OSError, JournalError, DatabaseError):
        return _deny('review_store_unavailable', 503)
    except ValueError:
        return _deny('signed_approval_not_accepted', 403)


@sensitive_post_parameters('credential')
@csrf_protect
def mufti_login(request):
    try:
        provider = _provider()
    except IdentityUnavailable:
        return _deny('trusted_identity_provider_not_configured', 503)
    if request.GET:
        return _deny('invalid_login_query', 400)
    message, status = '', 200
    if request.method == 'POST':
        try:
            if request.content_type != 'application/x-www-form-urlencoded':
                return _deny('native_login_required', 400)
            values = request.POST
            if set(values) != {'csrfmiddlewaretoken', 'credential'} or any(len(values.getlist(key)) != 1 for key in values):
                return _deny('invalid_login_fields', 400)
            identity = authenticate_identity(provider, values['credential'])
            validate_identity(identity, case_key=CASE_KEY)
        except (IdentityUnavailable, SuspiciousOperation):
            message, status = 'تعذر التحقق من هوية مفتي مخوّل لهذه القضية.', 403
        else:
            rotate_token(request)
            response = HttpResponse(status=303, headers={'Location': MUFTI_BASE})
            return _private(set_identity_cookie(request, response, provider, identity))
    get_token(request)
    return _private(render(request, 'mufti_review/login.html', {'message': message}, status=status), head=request.method == 'HEAD')


def mufti_page(request):
    provider, identity, denied = _actor(request)
    if denied is not None:
        return denied
    try:
        context = _context(request)
        context['identity'] = identity.subject_id
        if context['package'] and context['state'] == 'PENDING_REVIEW':
            command = secrets.token_hex(16)
            value = context['package']['request_sha256'] + '|' + command + '|' + identity.subject_id
            context.update(command_id=command, confirmation=browser_proof(request, DECISION_PURPOSE, value))
        get_token(request)
        return _private(render(request, 'mufti_review/review.html', context), head=request.method == 'HEAD')
    except InvalidSignedResponse:
        return _deny('invalid_review_query', 400)
    except (ValueError, OSError, JournalError, DatabaseError):
        return _deny('review_snapshot_unavailable', 503)


@sensitive_post_parameters('note')
@csrf_protect
def mufti_decide(request):
    provider, identity, denied = _actor(request)
    if denied is not None:
        return denied
    try:
        values = _form(request, {'csrfmiddlewaretoken', 'request_sha256', 'confirmation', 'command_id',
                                'split', 'action', 'note', 'acknowledge'})
        if services.HEX32.fullmatch(values['command_id']) is None:
            return _deny('invalid_review_command', 400)
        value = values['request_sha256'] + '|' + values['command_id'] + '|' + identity.subject_id
        if not compare_digest(browser_proof(request, DECISION_PURPOSE, value), values['confirmation']):
            return _deny('decision_browser_confirmation_invalid', 403)
        directory, maximum = author_http._configuration()
        result = services.record_decision(directory=directory, case_key=CASE_KEY,
            max_chars=maximum, split=values['split'] == '1', request_sha256=values['request_sha256'],
            subject_id=identity.subject_id, provider=provider, action=values['action'], note=values['note'],
            command_id=values['command_id'], synthetic_fixtures_only=True)
        return _private(render(request, 'mufti_review/decided.html', {'decision': result}))
    except (InvalidSignedResponse, SuspiciousOperation):
        return _deny('invalid_review_form', 400)
    except IdentityUnavailable:
        return _deny('current_mufti_identity_required', 403)
    except (services.ReviewConflict, HandoffBlocked, SegmentationNeedsReview):
        return _deny('review_stale_or_already_decided', 409)
    except (ValueError, OSError, JournalError, DatabaseError):
        return _deny('decision_store_unavailable', 503)


def decision_export(request):
    provider, identity, denied = _actor(request)
    if denied is not None:
        return denied
    try:
        context = _context(request)
        current = context['current']
        if not context['package'] or not current or not current['decision_id']:
            return _deny('current_decision_not_available', 409)
        decision = ReviewDecision.objects.get(request_id=current['request_sha256'])
        export = {'schema': 'fatwa.human-review-export.v1', 'status': 'HUMAN_REVIEW_ONLY_NOT_SIGNED',
            'request': context['package'], 'decision': current, 'reviewer_id': decision.subject_id}
        response = JsonResponse(export, json_dumps_params={'ensure_ascii': False})
        response['Content-Disposition'] = 'attachment; filename="human-review.json"'
        return _private(response, head=request.method == 'HEAD')
    except InvalidSignedResponse:
        return _deny('invalid_review_query', 400)
    except (ValueError, OSError, JournalError, DatabaseError, ReviewDecision.DoesNotExist):
        return _deny('review_export_unavailable', 503)


@csrf_protect
def mufti_logout(request):
    rotate_token(request)
    response = HttpResponse(status=303, headers={'Location': MUFTI_LOGIN})
    response.delete_cookie(COOKIE, path='/review/', samesite='Strict')
    return _private(response)


class ReviewDeskGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _enabled():
            return _deny('human_review_profile_disabled', 503)
        if request.META.get('REMOTE_ADDR') not in ('127.0.0.1', '::1'):
            return _deny('loopback_training_only', 403)
        methods = {
            AUTHOR_BASE: ('GET', 'HEAD'), AUTHOR_BASE + 'login/': ('GET', 'HEAD', 'POST'),
            AUTHOR_BASE + 'request.json': ('GET', 'HEAD'), AUTHOR_BASE + 'desk.css': ('GET', 'HEAD'),
            AUTHOR_BASE + 'review/': ('POST',), AUTHOR_BASE + 'receipt/': ('POST',),
            MUFTI_LOGIN: ('GET', 'HEAD', 'POST'), '/review/mufti/logout/': ('POST',),
            MUFTI_BASE: ('GET', 'HEAD'), MUFTI_BASE + 'record/': ('POST',),
            MUFTI_BASE + 'decision.json': ('GET', 'HEAD'),
        }
        if request.path not in methods:
            return _deny('not_found', 404)
        if request.method not in methods[request.path]:
            response = _deny('method_not_allowed', 405)
            response['Allow'] = ', '.join(methods[request.path])
            return response
        try:
            length = int(request.META.get('CONTENT_LENGTH') or '0')
        except ValueError:
            return _deny('invalid_request_length', 400)
        if not 0 <= length <= 65536:
            return _deny('request_too_large', 413)
        return _private(self.get_response(request), head=request.method == 'HEAD')
