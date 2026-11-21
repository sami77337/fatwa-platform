"""The final session callback cannot outrun already retained suppression pins."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.operational_workspace import views as operational_views
from apps.staff_sessions import middleware as session_middleware
from apps.staff_sessions.authority import ReauthenticationRule, SessionAuthority

from . import services
from .test_http import HTTPFixture
from .test_support import FEATURES


class CurrentSessionAuthority(SessionAuthority):
    def __init__(self, directory):
        self.directory = directory
        self.until = timezone.now() + timedelta(minutes=20)
        self.hook = None

    def projection_epoch(self):
        return repr((self.directory.provider_id, self.until.isoformat()))

    def permits(self, **values):
        actor = self.directory.identities.get(values["subject_id"])
        resource = values["resource"]
        allowed = bool(
            actor
            and values["provider_id"] == self.directory.provider_id
            and values["role"] == actor.role
            and values["auth_epoch"] == actor.auth_epoch
            and values["action"] in {"ISSUE", "USE"}
            and resource["provider_id"] == self.directory.provider_id
            and resource["subject_id"] == actor.subject_id
            and resource["surface"] == "OPERATIONS"
            and self.until > timezone.now()
        )
        if self.hook:
            self.hook(values)
        return allowed

    def reauthentication(self, **values):
        return ReauthenticationRule(True, 90)


@override_settings(**FEATURES)
class SuppressionSessionTests(HTTPFixture, TransactionTestCase):
    def test_last_session_callback_withholds_already_rendered_operational_case(self):
        authority = CurrentSessionAuthority(self.directory)
        plan = self.plan()
        original, armed, fired, final_stage = operational_views.render, False, False, False
        original_final = session_middleware._check

        def final_check(*args, **kwargs):
            nonlocal final_stage
            final_stage = True
            return original_final(*args, **kwargs)

        def render(*args, **kwargs):
            nonlocal armed
            response = original(*args, **kwargs)
            armed = True
            return response

        def last(values):
            nonlocal fired
            if armed and final_stage and not fired and values["action"] == "USE":
                fired = True
                with services.apply(plan=plan, confirmed=True, **self.suppression_common()):
                    pass

        middleware = ["apps.staff_sessions.middleware.SessionContext", *FEATURES["MIDDLEWARE"]]
        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=authority,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="synthetic-suppression-session-runtime-0001",
            MIDDLEWARE=middleware,
        ):
            self.assertEqual(self.login().status_code, 200)
            self.assertContains(self.client.get("/casework/operations/"), self.case.public_ref)
            authority.hook = last
            with (
                patch.object(operational_views, "render", side_effect=render),
                patch.object(session_middleware, "_check", side_effect=final_check),
            ):
                refused = self.client.get("/casework/operations/")
            self.assertTrue(fired)
            self.assertEqual(refused.status_code, 404)
            self.assertNotIn(self.case.public_ref.encode(), refused.content)
            self.assertEqual(refused["Referrer-Policy"], "no-referrer")
            authority.hook = None
        # A current restoration does not recover any revoked session or grant.
        self.change("RESTORE")
        self.assertTrue(self.read())
