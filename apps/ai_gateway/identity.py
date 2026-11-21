"""Keep the authenticated browser session alive through long provider boundaries."""

import json
from dataclasses import replace
from datetime import datetime

from django.utils import timezone

from apps.casework_web.access import COOKIE, SALT, TTL, RequestDirectory, current_staff
from apps.casework_web.views import _provider
from apps.mufti_review.identity import IdentityUnavailable


class SessionDirectory(RequestDirectory):
    """Current directory epoch plus the exact request's signed session deadline."""

    def __init__(self, request, directory, actor):
        super().__init__(directory, actor, authenticated_provider_id=directory.provider_id)
        self._request = request
        try:
            self._saved = request.get_signed_cookie(COOKIE, default="", salt=SALT, max_age=TTL)
            self._until = datetime.fromisoformat(json.loads(self._saved)["until"])
            self._check_session()
        except (ValueError, TypeError, KeyError) as exc:
            raise IdentityUnavailable("ai_gateway_session_required") from exc

    def _check_session(self):
        current = self._request.get_signed_cookie(COOKIE, default="", salt=SALT, max_age=TTL)
        if (
            current != self._saved
            or not timezone.is_aware(self._until)
            or self._until <= timezone.now()
        ):
            raise IdentityUnavailable("ai_gateway_session_expired_or_changed")

    def projection_epoch(self):
        self._check_session()
        return repr((super().projection_epoch(), self._until.isoformat()))

    def resolve(self, subject_id):
        self._check_session()
        actor = current_staff(self._request, self._provider)
        if (
            subject_id != self._subject
            or actor.subject_id != self._subject
            or actor.auth_epoch != self._epoch
            or self._provider.provider_id != self.provider_id
        ):
            raise IdentityUnavailable("ai_gateway_session_identity_changed")
        return replace(actor, valid_until=min(actor.valid_until, self._until))


def principal(request):
    directory = _provider()
    actor = current_staff(request, directory)
    return actor, SessionDirectory(request, directory, actor)
