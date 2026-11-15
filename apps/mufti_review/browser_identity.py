"""Short-lived, CSRF-bound sessions from an explicit trusted MUFTI directory."""
from datetime import datetime, timedelta
from hmac import compare_digest
import json
import re
from django.utils import timezone
from apps.editorial_workbench.reviewer_access import browser_proof
from .identity import IdentityUnavailable, resolve_identity, validate_identity

COOKIE = 'fatwa_training_mufti'
SALT = 'fatwa.mufti-review.session.v1'
TTL = 15 * 60
HEX = re.compile(r'[a-f0-9]{64}')


def _binding(request, provider_id, subject, epoch, until):
    return browser_proof(request, 'mufti.review.identity.v1',
        json.dumps([provider_id, subject, epoch, until], separators=(',', ':')))


def set_identity_cookie(request, response, provider, identity):
    validate_identity(identity)
    until = min(identity.valid_until, timezone.now() + timedelta(seconds=TTL)).isoformat()
    values = {'provider': provider.provider_id, 'subject': identity.subject_id,
        'epoch': identity.auth_epoch, 'until': until,
        'binding': _binding(request, provider.provider_id, identity.subject_id, identity.auth_epoch, until)}
    response.set_signed_cookie(COOKIE, json.dumps(values, separators=(',', ':')),
        salt=SALT, max_age=TTL, httponly=True, samesite='Strict', path='/review/')
    return response


def current_identity(request, provider, *, case_key):
    saved = request.get_signed_cookie(COOKIE, default='', salt=SALT, max_age=TTL)
    try:
        if type(saved) is not str or not 1 <= len(saved) <= 2048:
            raise ValueError('missing_cookie')
        values = json.loads(saved)
        if (type(values) is not dict or set(values) != {'provider', 'subject', 'epoch', 'until', 'binding'}
            or any(type(value) is not str for value in values.values())
            or HEX.fullmatch(values['binding']) is None):
            raise ValueError('invalid_cookie')
        until = datetime.fromisoformat(values['until'])
        if not timezone.is_aware(until) or until.utcoffset() != timedelta(0) or until <= timezone.now():
            raise ValueError('expired_cookie')
        identity = resolve_identity(provider, values['subject'], case_key=case_key)
        if values['provider'] != provider.provider_id or values['epoch'] != identity.auth_epoch:
            raise ValueError('identity_epoch_changed')
        expected = _binding(request, values['provider'], values['subject'], values['epoch'], values['until'])
        if not compare_digest(expected, values['binding']):
            raise ValueError('browser_binding_missing')
        return identity
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise IdentityUnavailable('mufti_session_not_authorized') from exc
