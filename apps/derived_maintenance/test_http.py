"""Native forms through the actual campaign guard, CSRF and response middleware."""

from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.ai_gateway.models import CandidateBatch
from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument
from apps.casework import services as cases
from tests.casework.test_http import hidden

from . import services, views
from .models import DerivativeClear, DerivativeRebuild
from .test_support import FEATURES, Fixture


def send(client, path, fields, page):
    return client.post(
        path,
        urlencode({"csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), **fields}),
        content_type="application/x-www-form-urlencoded",
    )


class HTTPFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def login(self):
        path = "/casework/staff/login/"
        page = self.client.get(path)
        response = send(
            self.client, path, {"credential": "synthetic-editor-credential-32-characters"}, page
        )
        self.assertEqual(response.status_code, 303, response.content)
        return self.client.get(views.STAFF_PATH)

    def item(self, page, kind="SEARCH_INDEX"):
        result = send(
            self.client,
            views.STAFF_PATH,
            dict(
                action="dm_inspect",
                kind=kind,
                identifier=self.built["generation_id"]
                if kind == "SEARCH_INDEX"
                else self.run["id"],
            ),
            page,
        )
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def preview_native(self, page, *, fragment=""):
        fields = {
            key: hidden(page, key)
            for key in (
                "operation",
                "kind",
                "identifier",
                "header_digest",
                "payload_digest",
                "clearance",
                "watermark",
                "request_key",
            )
        }
        return send(
            self.client,
            views.STAFF_PATH,
            {
                "action": "dm_preview",
                **fields,
                "reason": "إجراء اصطناعي <script>لا ينفذ</script>",
                "fragment": fragment,
            },
            page,
        )

    def confirm_fields(self, page):
        return dict(
            action="dm_apply",
            plan=hidden(page, "plan"),
            proof=hidden(page, "proof"),
            confirmed="yes",
        )

    def confirm(self, page):
        return send(self.client, views.STAFF_PATH, self.confirm_fields(page), page)


@override_settings(**FEATURES)
class DerivedNativeTests(HTTPFixture, TransactionTestCase):
    def test_native_clear_then_rebuild_search_and_ai_without_source_content_in_audit(self):
        page = self.login()
        self.assertEqual(page.status_code, 200, page.content)
        for kind in ("SEARCH_INDEX", "AI_CANDIDATES"):
            item = self.item(self.client.get(views.STAFF_PATH), kind)
            self.assertNotContains(item, self.source_text)
            preview = self.preview_native(item)
            self.assertContains(preview, "مراجعة إجراء المشتق قبل اعتماده")
            count = DerivativeClear.objects.count()
            self.assertContains(self.confirm(preview), 'data-result="CLEAR"')
            self.assertEqual(DerivativeClear.objects.count(), count + 1)
            self.assertEqual(self.confirm(preview).status_code, 409)
            item = self.item(self.client.get(views.STAFF_PATH), kind)
            self.assertContains(item, 'data-state="CLEARED"')
            self.assertContains(item, "&lt;script&gt;")
            preview = self.preview_native(
                item, fragment="عبارة محددة" if kind == "AI_CANDIDATES" else ""
            )
            rebuilt = self.confirm(preview)
            self.assertContains(rebuilt, 'data-result="REBUILD"')
            if kind == "AI_CANDIDATES":
                self.assertContains(rebuilt, 'id="derived-rebuilt-candidates"')
                self.assertContains(rebuilt, '<html lang="ar" dir="rtl">')
                self.assertContains(rebuilt, self.source_text[:12])
                composer = send(
                    self.client,
                    "/casework/staff/",
                    {"action": "precise_open", "case_ref": self.receipt["public_ref"]},
                    rebuilt,
                )
                self.assertEqual(composer.status_code, 200, composer.content)
                self.assertContains(composer, 'id="precise-compose"')
        self.assertEqual(DerivativeClear.objects.count(), 2)
        self.assertEqual(DerivativeRebuild.objects.count(), 2)
        self.assertFalse(
            SearchDocument.objects.filter(generation_id=self.built["generation_id"]).exists()
        )
        self.assertFalse(CandidateBatch.objects.filter(run_id=self.run["id"]).exists())
        self.assertEqual(len(self.ai_provider.calls), 2)
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)

    def test_native_csrf_proof_binding_and_unknown_operations_do_not_mutate(self):
        page = self.login()
        self.assertEqual(self.client.post(views.STAFF_PATH, {"action": "dm_open"}).status_code, 403)
        self.assertEqual(self.client.get(views.STAFF_PATH + "?action=CLEAR").status_code, 400)
        preview = self.preview_native(self.item(page))
        fields = self.confirm_fields(preview)
        fields["plan"] = fields["plan"].replace('"CLEAR"', '"REBUILD"')
        self.assertEqual(send(self.client, views.STAFF_PATH, fields, preview).status_code, 400)
        self.assertEqual(self.journal.snapshot(), [])
        self.assertEqual(DerivativeClear.objects.count(), 0)

    def test_last_render_revoke_rolls_back_sql_and_retains_external_clearance(self):
        preview = self.preview_native(self.item(self.login()))
        original = views.render

        def render(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[1] == "derived_maintenance/saved.html":
                self.maintenance_authority.denied.add(("editor", "CLEAR"))
            return response

        with patch.object(views, "render", side_effect=render):
            refused = self.confirm(preview)
        self.assertEqual(refused.status_code, 409)
        self.assertNotIn(b"data-result=", refused.content)
        self.assertEqual(DerivativeClear.objects.count(), 0)
        self.assertEqual(len(self.journal.snapshot()), 1)
        with self.assertRaises(cases.CaseConflict):
            search.search(**self.common, value="اصطناعي")
        page = self.client.get(views.STAFF_PATH)
        self.assertContains(page, 'data-action="reconcile"')
        self.assertContains(self.confirm(self.preview_native(page)), 'data-result="RECONCILE"')
        self.assertTrue(DerivativeClear.objects.get().recovered)
        self.assertEqual(SearchDocument.objects.count(), 0)

    def test_late_search_render_cannot_return_a_just_cleared_snippet(self):
        from apps.canonical_search import views as search_views

        page = self.login()
        plan, original = self.plan(), search_views.render

        def render(*args, **kwargs):
            response = original(*args, **kwargs)
            with services.apply(plan=plan, confirmed=True, **self.base):
                pass
            return response

        with patch.object(search_views, "render", side_effect=render):
            result = send(
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
        self.assertNotEqual(result.status_code, 200)
        self.assertNotIn(b"canonical-hit", result.content)
        self.assertEqual(result["Referrer-Policy"], "no-referrer")

    def test_regenerated_preview_rechecks_source_and_management_after_last_render(self):
        from apps.ai_gateway import services as gateway
        from apps.ai_gateway.models import GatewayRun

        self.login()
        self.change(kind="AI_CANDIDATES")
        original = views.render
        for permission in ("SOURCE_READ", "MANAGEMENT_REBUILD"):
            with self.subTest(permission=permission):
                preview = self.preview_native(
                    self.item(self.client.get(views.STAFF_PATH), "AI_CANDIDATES"),
                    fragment="عبارة محددة",
                )
                fired = False

                def render(*args, **kwargs):
                    nonlocal fired
                    response = original(*args, **kwargs)
                    if args[1] == "derived_maintenance/saved.html":
                        fired = True
                        if permission == "SOURCE_READ":
                            self.authority.denied.add("READ")
                        else:
                            self.maintenance_authority.denied.add(("editor", "REBUILD"))
                    return response

                with patch.object(views, "render", side_effect=render):
                    refused = self.confirm(preview)
                self.assertTrue(fired)
                self.assertNotEqual(refused.status_code, 200)
                self.assertNotIn(b"derived-rebuilt-candidates", refused.content)
                self.assertNotIn(self.source_text[:12].encode(), refused.content)
                self.authority.denied.clear()
                self.maintenance_authority.denied.clear()
                latest = (
                    GatewayRun.objects.filter(case_id=self.receipt["case_id"])
                    .order_by("-created_at")
                    .first()
                )
                with gateway.read_boundary(**self.common, run_id=str(latest.pk)) as current:
                    self.assertEqual(len(current["candidates"]), 1)
                self.assertFalse(CandidateBatch.objects.filter(run_id=self.run["id"]).exists())

    def test_late_ai_render_cannot_return_a_just_cleared_candidate(self):
        from apps.ai_gateway import panel
        from apps.ai_gateway import test_http as ai_http
        from apps.ai_gateway.models import GatewayRun

        page = self.login()
        composer = send(
            self.client,
            "/casework/staff/",
            {"action": "precise_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(composer.status_code, 200, composer.content)
        result = ai_http.NativeFixture.ai_post(
            self,
            self.client,
            hidden(composer, "csrfmiddlewaretoken"),
            ai_http.initial_state(composer),
        )
        self.assertEqual(result.status_code, 200, result.content)
        run = GatewayRun.objects.order_by("-created_at").first()
        self.run = {"id": str(run.pk)}
        self.maintenance_authority.choices = (
            *self.maintenance_authority.choices,
            ("AI_CANDIDATES", str(run.pk)),
        )
        plan, original = self.plan(kind="AI_CANDIDATES"), panel.django_render

        def render(*args, **kwargs):
            response = original(*args, **kwargs)
            with services.apply(plan=plan, confirmed=True, **self.base):
                pass
            return response

        with patch.object(panel, "django_render", side_effect=render):
            refused = ai_http.NativeFixture.ai_post(
                self,
                self.client,
                hidden(composer, "csrfmiddlewaretoken"),
                ai_http.states(result)[0],
                "open",
            )
        self.assertNotEqual(refused.status_code, 200)
        self.assertNotIn("مصدر اصطناعي".encode(), refused.content)
        self.assertNotIn(b"data-ai-handoff", refused.content)
