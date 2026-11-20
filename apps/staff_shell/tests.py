"""True campaign asset/default-off/CSP tests; assets never read a private case."""

import io

from django.test import Client, TransactionTestCase, override_settings
from PIL import Image


@override_settings(FATWA_CASEWORK_WEB_ENABLED=True, ROOT_URLCONF="config.campaign_urls")
class StaffShellHTTPTests(TransactionTestCase):
    def client_for(self):
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def test_default_closed_and_unknown_private_paths_are_not_installation_assets(self):
        client = self.client_for()
        self.assertEqual(client.get("/casework/staff/pwa/manifest.webmanifest").status_code, 404)
        with override_settings(FATWA_STAFF_PWA_ENABLED=True):
            for path in ("/casework/staff/pwa/private.json", "/casework/staff/pwa/../answer.json"):
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.post("/casework/staff/pwa/sw.mjs").status_code, 405)
            self.assertEqual(client.get("/casework/staff/pwa/sw.mjs?case=private").status_code, 400)
        page = client.get("/casework/staff/login/")
        self.assertNotIn(b'data-staff-pwa="enabled"', page.content)
        self.assertNotIn("script-src", page["Content-Security-Policy"])

    @override_settings(FATWA_STAFF_PWA_ENABLED=True)
    def test_exact_manifest_scope_real_icons_script_policy_and_private_response_headers(self):
        client = self.client_for()
        manifest = client.get("/casework/staff/pwa/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        data = manifest.json()
        self.assertEqual((data["scope"], data["start_url"], data["display"]),
                         ("/casework/staff/", "/casework/staff/", "standalone"))
        for icon in data["icons"]:
            response = client.get(icon["src"])
            self.assertEqual(response.status_code, 200)
            with Image.open(io.BytesIO(response.content)) as image:
                image.verify()
                self.assertEqual(f"{image.width}x{image.height}", icon["sizes"])
            self.assertIn("no-store", response["Cache-Control"])
        worker = client.get("/casework/staff/pwa/sw.mjs")
        self.assertEqual(worker["Service-Worker-Allowed"], "/casework/staff/")
        self.assertIn(b'request.method !== "GET"', worker.content)
        self.assertNotIn(b"caches.open", worker.content)
        page = client.get("/casework/staff/login/")
        self.assertContains(page, 'data-staff-pwa="enabled"')
        for directive in ("script-src 'self'", "worker-src 'self'", "manifest-src 'self'"):
            self.assertIn(directive, page["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", page["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", page["Content-Security-Policy"])
        requester = client.get("/casework/status/")
        self.assertNotIn(b'data-staff-pwa="enabled"', requester.content)
        self.assertNotIn("worker-src", requester["Content-Security-Policy"])
