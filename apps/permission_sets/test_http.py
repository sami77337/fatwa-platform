from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.operational_workspace.test_support import CREDENTIALS
from tests.casework.test_http import hidden

from . import catalog, store, views
from .models import PermissionRevision
from .test_support import FEATURES, Fixture


def send(client, path, fields, page):
    return client.post(
        path,
        urlencode(
            {"csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), **fields}, doseq=True
        ),
        content_type="application/x-www-form-urlencoded",
    )


class HTTPFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.seeded()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def login(self, *, subject="admin", staff=False, client=None):
        client = client or self.client
        login = "/casework/staff/login/" if staff else "/casework/operations/login/"
        page = client.get(login)
        response = send(client, login, {"credential": CREDENTIALS[subject]}, page)
        self.assertEqual(response.status_code, 303, response.content)
        return client.get(views.STAFF_PATH if staff else views.OPERATIONAL_PATH)

    def item(self, page, *, kind="USER", key="operator", path=views.OPERATIONAL_PATH):
        response = send(self.client, path, {"action": "ps_inspect", "kind": kind, "key": key}, page)
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def fields(self, page, *, deny_add=True):
        fields = {
            key: hidden(page, key)
            for key in ("kind", "key", "change", "expected_digest", "request_key")
        }
        return {
            **fields,
            "action": "ps_preview",
            "sets": [self.template_key],
            "deny": [catalog.digest(self.scopes["ADD_INTERNAL_NOTE"])] if deny_add else [],
            "note": "رفض فردي <script>لا ينفذ</script>",
            "minutes": "5",
        }

    def confirm(self, page):
        return {
            "action": "ps_apply",
            "plan": hidden(page, "plan"),
            "proof": hidden(page, "proof"),
            "confirmed": "yes",
        }


@override_settings(**FEATURES)
class PermissionHTTPTests(HTTPFixture, TransactionTestCase):
    def test_new_template_is_only_created_after_exact_rule_mandates_and_confirmation(self):
        page = self.login()
        created = send(self.client, views.OPERATIONAL_PATH, {"action": "ps_new"}, page)
        self.assertEqual(created.status_code, 200, created.content)
        key = hidden(created, "key")
        values = {
            name: hidden(created, name)
            for name in ("kind", "key", "change", "expected_digest", "request_key")
        } | {
            "action": "ps_preview",
            "title": "قالب جديد محدد",
            "minutes": "5",
            "note": "تفويض إنشاء الموارد المحددة",
            "allow": [catalog.digest(self.scopes["READ_CASE"])],
        }
        self.assertEqual(
            send(self.client, views.OPERATIONAL_PATH, values, created).status_code, 409
        )
        self.assertEqual(PermissionRevision.objects.count(), 2)
        self.authority.allow_set(key)
        preview = send(self.client, views.OPERATIONAL_PATH, values, created)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(PermissionRevision.objects.count(), 2)
        saved = send(self.client, views.OPERATIONAL_PATH, self.confirm(preview), preview)
        self.assertContains(saved, 'id="ps-saved"')
        self.assertEqual(
            PermissionRevision.objects.get(scope_key=key).definition["title"], "قالب جديد محدد"
        )

    def test_admin_previews_actual_user_deny_and_immutable_audit_then_restores_use(self):
        page = self.login()
        self.assertContains(page, "قوالب الصلاحيات")
        item = self.item(page)
        preview = send(self.client, views.OPERATIONAL_PATH, self.fields(item), item)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertContains(preview, 'data-affected="operator"')
        self.assertContains(preview, "&lt;script&gt;لا ينفذ&lt;/script&gt;")
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        saved = send(self.client, views.OPERATIONAL_PATH, self.confirm(preview), preview)
        self.assertContains(saved, 'id="ps-saved"')
        self.assertIn("no-store", saved["Cache-Control"])
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        item = self.item(saved)
        self.assertContains(item, 'data-version="2"')
        self.assertContains(item, "ORGANIZER_ADMIN")
        self.assertEqual(PermissionRevision.objects.count(), 3)
        preview = send(self.client, views.OPERATIONAL_PATH, self.fields(item, deny_add=False), item)
        self.assertEqual(preview.status_code, 200, preview.content)
        saved = send(self.client, views.OPERATIONAL_PATH, self.confirm(preview), preview)
        self.assertContains(saved, 'id="ps-saved"')
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        self.note("إضافة من المسار الفعلي بعد إزالة الرفض الإداري")
        self.assert_original()

    def test_current_mufti_session_uses_same_explicit_admin_contract(self):
        page = self.login(subject="mufti", staff=True)
        self.assertEqual(page.status_code, 200, page.content)
        item = self.item(page, path=views.STAFF_PATH)
        preview = send(self.client, views.STAFF_PATH, self.fields(item), item)
        self.assertEqual(preview.status_code, 200, preview.content)
        saved = send(self.client, views.STAFF_PATH, self.confirm(preview), preview)
        self.assertContains(saved, 'id="ps-saved"')
        self.assertEqual(
            PermissionRevision.objects.order_by("created_at").last().actor_role, "MUFTI"
        )
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.assert_original()

    def test_native_template_change_previews_affected_users_and_requires_new_review(self):
        item = self.item(self.login(), kind="SET", key=self.template_key)
        values = {
            key: hidden(item, key)
            for key in ("kind", "key", "change", "expected_digest", "request_key")
        }
        values |= {
            "action": "ps_preview",
            "title": "قالب القراءة فقط",
            "minutes": "5",
            "note": "سحب الإضافة مع حفظ القراءة",
            "allow": [
                catalog.digest(value)
                for action, value in self.scopes.items()
                if action != "ADD_INTERNAL_NOTE"
            ],
        }
        preview = send(self.client, views.OPERATIONAL_PATH, values, item)
        self.assertContains(preview, 'data-affected="operator"')
        self.assertContains(preview, catalog.LABELS["ADD_INTERNAL_NOTE"])
        saved = send(self.client, views.OPERATIONAL_PATH, self.confirm(preview), preview)
        self.assertContains(saved, 'id="ps-saved"')
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.assertTrue(self.allowed("READ_INTERNAL_NOTES"))
        repeated = send(self.client, views.OPERATIONAL_PATH, self.confirm(preview), preview)
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(PermissionRevision.objects.count(), 3)

    def test_csrf_exact_fields_confirmed_proof_and_self_protection(self):
        item = self.item(self.login())
        values = self.fields(item)
        self.assertEqual(self.client.post(views.OPERATIONAL_PATH, values).status_code, 403)
        for fields in (
            {**values, "role": "MUFTI"},
            {**values, "key": ["operator", "admin"]},
            {**values, "allow": ["*"]},
        ):
            self.assertEqual(
                send(self.client, views.OPERATIONAL_PATH, fields, item).status_code, 400
            )
        preview = send(self.client, views.OPERATIONAL_PATH, values, item)
        confirm = self.confirm(preview)
        for fields in ({**confirm, "proof": "f" * 64}, {**confirm, "confirmed": "no"}):
            self.assertEqual(
                send(self.client, views.OPERATIONAL_PATH, fields, preview).status_code, 400
            )
        own = self.item(item, key="admin")
        self.assertNotContains(own, 'id="ps-edit"')
        self.assertNotContains(own, 'id="ps-disable"')
        self.assertEqual(PermissionRevision.objects.count(), 2)

    def test_last_native_render_denial_discards_saved_body_and_rolls_back_revision(self):
        item = self.item(self.login())
        preview = send(self.client, views.OPERATIONAL_PATH, self.fields(item), item)
        before = store.fingerprint()
        render = views.render

        def late(*args, **kwargs):
            response = render(*args, **kwargs)
            self.authority.revoke("WRITE_USER", target="operator")
            return response

        with patch.object(views, "render", side_effect=late):
            response = send(self.client, views.OPERATIONAL_PATH, self.confirm(preview), preview)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(b"ps-saved", response.content)
        self.assertEqual(store.fingerprint(), before)
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))

    def test_closed_route_remote_query_default_off_and_organizer_have_no_management(self):
        self.assertEqual(self.client.get(views.OPERATIONAL_PATH).status_code, 409)
        self.assertEqual(
            Client(REMOTE_ADDR="203.0.113.5", HTTP_HOST="127.0.0.1")
            .get(views.OPERATIONAL_PATH)
            .status_code,
            403,
        )
        self.assertEqual(
            self.client.get(views.OPERATIONAL_PATH, {"user": "operator"}).status_code, 400
        )
        with override_settings(FATWA_PERMISSION_SETS_ENABLED=False):
            self.assertEqual(self.client.get(views.OPERATIONAL_PATH).status_code, 404)
        page = self.login(subject="operator")
        self.assertEqual(page.status_code, 409)
        self.assertEqual(PermissionRevision.objects.count(), 2)
