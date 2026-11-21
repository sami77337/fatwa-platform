"""Independent short-lived CSRF-bound session; never a Mufti session conversion."""

import json
from datetime import datetime, timedelta
from hmac import compare_digest

from django.utils import timezone

from apps.casework.services import CaseConflict
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.mufti_review.identity import IdentityUnavailable
from apps.staff_sessions import integration as sessions

from . import identity

COOKIE = "fatwa_operational_staff"
SALT = "fatwa.operational.session.v1"
BASE = "/casework/operations/"
TTL = 600


def binding(request, values):
    return browser_proof(request, SALT, json.dumps(values, sort_keys=True, separators=(",", ":")))


def set_cookie(request, response, directory, actor):
    identity.configured(directory)
    identity.validate(actor)
    values = {
        "provider": directory.provider_id,
        "subject": actor.subject_id,
        "role": actor.role,
        "epoch": actor.auth_epoch,
        "until": min(actor.valid_until, timezone.now() + timedelta(seconds=TTL)).isoformat(),
    }
    values["binding"] = binding(request, values)
    try:
        sessions.issue_cookie(
            request,
            values,
            directory,
            actor,
            surface="OPERATIONS",
            deadline=datetime.fromisoformat(values["until"]),
        )
    except IdentityUnavailable as exc:
        raise CaseConflict("operational_session_unavailable") from exc
    response.set_signed_cookie(
        COOKIE,
        json.dumps(values, separators=(",", ":")),
        salt=SALT,
        max_age=TTL,
        httponly=True,
        samesite="Strict",
        path=BASE,
        secure=False,
    )
    return response


def current(request, directory):
    try:
        saved = request.get_signed_cookie(COOKIE, default="", salt=SALT, max_age=TTL)
        if type(saved) is not str or not 1 <= len(saved) <= 2048:
            raise ValueError
        values = json.loads(saved)
        if (
            type(values) is not dict
            or set(values)
            != {"provider", "subject", "role", "epoch", "until", "binding"} | sessions.fields()
            or any(type(value) is not str for value in values.values())
        ):
            raise ValueError
        original_values = dict(values)
        signature = values.pop("binding")
        values.pop("session_id", None)
        until = datetime.fromisoformat(values["until"])
        if not identity.valid_deadline(until) or not compare_digest(
            signature, binding(request, values)
        ):
            raise ValueError
        actor = identity.resolve(directory, values["subject"])
        if (values["provider"], values["role"], values["epoch"]) != (
            directory.provider_id,
            actor.role,
            actor.auth_epoch,
        ):
            raise ValueError
        sessions.current_cookie(
            request, original_values, directory, actor, surface="OPERATIONS", deadline=until
        )
        return actor, min(actor.valid_until, until)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise CaseConflict("operational_session_unavailable") from exc
