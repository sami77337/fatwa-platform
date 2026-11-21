"""A last native session callback cannot release an already cleared search result."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.canonical_search import services as search
from apps.canonical_search import views as search_views
from apps.staff_sessions import middleware
from apps.staff_sessions.authority import ReauthenticationRule, SessionAuthority

from . import services
from .test_http import HTTPFixture, send
from .test_support import FEATURES


class Sessions(SessionAuthority):
    def __init__(self, directory):
        self.directory, self.hook = directory, None
        self.until = timezone.now() + timedelta(minutes=20)

    def projection_epoch(self):
        return repr((self.directory.provider_id, self.until.isoformat()))

    def permits(self, **values):
        actor = self.directory.identities.get(values["subject_id"])
        resource = values["resource"]
        permitted = bool(
            actor
            and values["provider_id"] == self.directory.provider_id
            and values["role"] == actor.role
            and values["auth_epoch"] == actor.auth_epoch
            and values["action"] in {"ISSUE", "USE"}
            and resource["provider_id"] == self.directory.provider_id
            and resource["subject_id"] == actor.subject_id
            and resource["surface"] == "CASEWORK"
            and self.until > timezone.now()
        )
        if self.hook:
            self.hook(values)
        return permitted

    def reauthentication(self, **values):
        return ReauthenticationRule(True, 90)


@override_settings(**FEATURES)
class DerivedSessionTests(HTTPFixture, TransactionTestCase):
    def test_last_session_callback_removes_already_rendered_search_snippets(self):
        authority = Sessions(self.directory)
        plan = self.plan()
        original, final = search_views.render, middleware._check
        armed, final_stage, fired = False, False, False

        def render(*args, **kwargs):
            nonlocal armed
            result = original(*args, **kwargs)
            armed = True
            return result

        def final_check(*args, **kwargs):
            nonlocal final_stage
            final_stage = True
            return final(*args, **kwargs)

        def revoke(values):
            nonlocal fired
            if armed and final_stage and not fired and values["action"] == "USE":
                fired = True
                with services.apply(plan=plan, confirmed=True, **self.base):
                    pass

        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=authority,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="synthetic-derived-session-runtime-0001",
        ):
            page = self.login()
            self.assertEqual(page.status_code, 200, page.content)
            authority.hook = revoke
            with (
                patch.object(search_views, "render", side_effect=render),
                patch.object(middleware, "_check", side_effect=final_check),
            ):
                refused = send(
                    self.client,
                    "/casework/staff/",
                    dict(
                        action="cs_search",
                        case_ref=self.receipt["public_ref"],
                        query="اصطناعي",
                        mode="FTS",
                        kind="ALL",
                        page="1",
                        scope="CASE",
                    ),
                    page,
                )
            self.assertTrue(fired)
            self.assertEqual(refused.status_code, 404, refused.content)
            self.assertNotIn(b"canonical-hit", refused.content)
            self.assertEqual(refused["Referrer-Policy"], "no-referrer")
            authority.hook = None
        self.assertEqual(search.desk(**self.common)["state"], "CLEARED")
        self.change("REBUILD")
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)
