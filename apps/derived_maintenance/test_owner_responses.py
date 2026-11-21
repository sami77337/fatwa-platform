"""Actual session-response callbacks cannot reopen earlier owner/source permissions."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.ai_gateway import services as gateway
from apps.ai_gateway.models import GatewayRun
from apps.canonical_search import services as search
from apps.staff_sessions import middleware

from . import views
from .test_http import HTTPFixture
from .test_sessions import Sessions
from .test_support import FEATURES


@override_settings(**FEATURES)
class RetainedOwnerResponseTests(HTTPFixture, TransactionTestCase):
    def last_session_callback(self, kind, revoke):
        self.change(kind=kind)
        authority = Sessions(self.directory)
        render, check = views.render, middleware._check
        armed, final_stage, fired = False, False, False

        def rendered(*args, **kwargs):
            nonlocal armed
            response = render(*args, **kwargs)
            if args[1] == "derived_maintenance/saved.html":
                armed = True
            return response

        def checked(*args, **kwargs):
            nonlocal final_stage
            final_stage = True
            return check(*args, **kwargs)

        def latest(values):
            nonlocal fired
            if armed and final_stage and not fired and values["action"] == "USE":
                fired = True
                revoke()

        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=authority,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="synthetic-derived-owner-runtime-0001",
        ):
            item = self.item(self.login(), kind)
            preview = self.preview_native(
                item, fragment="عبارة محددة" if kind == "AI_CANDIDATES" else ""
            )
            authority.hook = latest
            with (
                patch.object(views, "render", side_effect=rendered),
                patch.object(middleware, "_check", side_effect=checked),
            ):
                refused = self.confirm(preview)
            self.assertTrue(armed)
            self.assertTrue(fired)
            self.assertEqual(refused.status_code, 404, refused.content)
            self.assertNotIn(b"data-result=", refused.content)
            self.assertNotIn(b"derived-rebuilt-candidates", refused.content)
            self.assertNotIn(self.source_text[:12].encode(), refused.content)
            self.assertEqual(refused["Referrer-Policy"], "no-referrer")
            authority.hook = None

    def test_last_native_session_callback_revokes_the_regenerated_source_read(self):
        self.last_session_callback("AI_CANDIDATES", lambda: self.authority.denied.add("READ"))
        self.authority.denied.clear()
        latest = (
            GatewayRun.objects.filter(case_id=self.receipt["case_id"])
            .order_by("-created_at")
            .first()
        )
        with gateway.read_boundary(**self.common, run_id=str(latest.pk)) as current:
            self.assertEqual(len(current["candidates"]), 1)

    def test_last_native_session_callback_revokes_the_completed_search_rebuild(self):
        self.last_session_callback(
            "SEARCH_INDEX", lambda: self.search_authority.denied.add("REBUILD")
        )
        self.search_authority.denied.clear()
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)
