from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.operational_workspace.test_support import CREDENTIALS
from tests.casework.test_http import hidden

from . import catalog, services, views
from .models import SuppressionEvent
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

    def login(self, subject="admin", *, client=None):
        client = client or self.client
        path = "/casework/operations/login/"
        page = client.get(path)
        response = send(client, path, {"credential": CREDENTIALS[subject]}, page)
        self.assertEqual(response.status_code, 303, response.content)
        return client.get(views.OPERATIONAL_PATH)

    def item(self, page):
        result = send(
            self.client,
            views.OPERATIONAL_PATH,
            {"action": "rs_inspect", "kind": "CASE", "identifier": self.receipt["case_id"]},
            page,
        )
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def preview(self, page):
        fields = {
            key: hidden(page, key)
            for key in (
                "kind",
                "identifier",
                "source_digest",
                "head",
                "watermark",
                "request_key",
                "operation",
            )
        }
        return send(
            self.client,
            views.OPERATIONAL_PATH,
            {"action": "rs_preview", **fields, "reason": "قرار إداري <script>لا ينفذ</script>"},
            page,
        )

    def confirm_fields(self, page):
        return {
            "action": "rs_apply",
            "plan": hidden(page, "plan"),
            "proof": hidden(page, "proof"),
            "confirmed": "yes",
        }

    def confirm(self, page):
        return send(self.client, views.OPERATIONAL_PATH, self.confirm_fields(page), page)


@override_settings(**FEATURES)
class SuppressionHTTPTests(HTTPFixture, TransactionTestCase):
    def test_native_preview_delete_audit_and_restore_preserve_original(self):
        page = self.item(self.login())
        self.assertNotContains(page, self.intake["original_question"])
        preview = self.preview(page)
        self.assertContains(preview, "مراجعة القرار قبل اعتماده")
        self.assertEqual(SuppressionEvent.objects.count(), 0)
        saved = self.confirm(preview)
        self.assertContains(saved, 'data-result="SOFT_DELETE"')
        self.assertEqual(self.confirm(preview).status_code, 409)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        item = self.item(self.client.get(views.OPERATIONAL_PATH))
        self.assertContains(item, 'data-state="SOFT_DELETED"')
        self.assertContains(item, "&lt;script&gt;")
        restored = self.confirm(self.preview(item))
        self.assertContains(restored, 'data-result="RESTORE"')
        self.assertEqual(self.read()["original_question"], self.intake["original_question"])
        self.assertEqual(SuppressionEvent.objects.count(), 2)

    def test_actual_organizer_cannot_admin_and_anonymous_csrf_and_get_mutation_fail(self):
        self.assertEqual(self.client.get(views.OPERATIONAL_PATH).status_code, 409)
        self.assertEqual(self.login("operator").status_code, 409)
        admin = self.login()
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(
            self.client.post(views.OPERATIONAL_PATH, {"action": "rs_open"}).status_code, 403
        )
        self.assertEqual(
            self.client.get(views.OPERATIONAL_PATH + "?action=SOFT_DELETE").status_code, 400
        )
        self.assertEqual(SuppressionEvent.objects.count(), 0)

    def test_changed_source_and_confirmation_proof_do_not_change_journal(self):
        preview = self.preview(self.item(self.login()))
        fields = self.confirm_fields(preview)
        fields["plan"] = fields["plan"].replace('"SOFT_DELETE"', '"RESTORE"')
        self.assertEqual(
            send(self.client, views.OPERATIONAL_PATH, fields, preview).status_code, 400
        )
        self.assertEqual(self.journal.snapshot(), [])
        self.assertEqual(SuppressionEvent.objects.count(), 0)

    def test_late_render_revoke_rolls_back_sql_and_native_reconciliation_retains_suppression(self):
        preview = self.preview(self.item(self.login()))
        original = views.render

        def render(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[1] == "record_suppression/saved.html":
                self.suppression_authority.revoke("SOFT_DELETE")
            return response

        with patch.object(views, "render", side_effect=render):
            failed = self.confirm(preview)
        self.assertEqual(failed.status_code, 409)
        self.assertNotIn(b"data-result=", failed.content)
        self.assertEqual(SuppressionEvent.objects.count(), 0)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        page = self.client.get(views.OPERATIONAL_PATH)
        self.assertContains(page, 'data-action="reconcile"')
        fields = {
            key: hidden(page, key)
            for key in (
                "kind",
                "identifier",
                "source_digest",
                "head",
                "watermark",
                "request_key",
                "operation",
            )
        }
        repair = send(
            self.client,
            views.OPERATIONAL_PATH,
            {"action": "rs_preview", **fields, "reason": "إعادة تطبيق القرار بعد التوقف"},
            page,
        )
        self.assertContains(repair, "RECONCILE")
        self.assertEqual(self.confirm(repair).status_code, 200)
        self.assertTrue(SuppressionEvent.objects.get().recovered)
        with self.assertRaises(catalog.SuppressionDenied):
            self.read()
        self.assertEqual(
            self.confirm(
                self.preview(self.item(self.client.get(views.OPERATIONAL_PATH)))
            ).status_code,
            200,
        )
        self.assertTrue(self.read())

    def test_last_requester_render_cannot_return_a_suppressed_case(self):
        from apps.requester_portal import views as requester_views

        original = requester_views.render
        plan = self.plan()
        fired = False

        def late(*args, **kwargs):
            nonlocal fired
            response = original(*args, **kwargs)
            if args[1] == "requester_portal/portal.html" and not fired:
                fired = True
                with services.apply(plan=plan, confirmed=True, **self.suppression_common()):
                    pass
            return response

        page = self.client.get("/casework/status/")
        unlocked = send(
            self.client,
            "/casework/status/",
            {"action": "unlock", "token": self.receipt["token"]},
            page,
        )
        self.assertEqual(unlocked.status_code, 303, unlocked.content)
        with patch.object(requester_views, "render", side_effect=late):
            response = self.client.get("/casework/status/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.case.public_ref.encode(), response.content)
        # The native request rolled back, but the external decision still vetoes use.
        self.change("RECONCILE")
        self.change("RESTORE")
        self.assertTrue(self.read())
