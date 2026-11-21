"""Real campaign HTTP, current release/use checks and response-time denial."""

import tempfile
import uuid
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.private_media.filesystem import FileSystemStorage
from apps.research_library import services as library
from apps.research_library.models import LibraryDecision, LibraryVersion
from apps.research_library.test_support import payload

from . import views
from .test_support import BASE, FEATURES, TEXT, APIFixture


class ReadCallbackStorage(FileSystemStorage):
    hook = None

    def get(self, original):
        raw = super().get(original)
        if self.hook:
            self.hook()
        return raw


@override_settings(**FEATURES)
class MaterialAPITests(APIFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def test_read_only_default_closed_and_uniform_contract_errors(self):
        with override_settings(FATWA_MATERIAL_API_ENABLED=False):
            self.assertEqual(self.client.get(BASE).json()["error"]["code"], "unavailable")
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)(BASE)
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response.json()["error"]["code"], "method_not_allowed")
            self.assertEqual(response["Allow"], "GET, HEAD")
        self.assertEqual(self.client.get(BASE + "private-case/" + str(uuid.uuid4()) + "/").status_code, 404)
        self.assertEqual(self.client.get(BASE, REMOTE_ADDR="192.0.2.10").status_code, 403)
        self.assertEqual(self.client.get(BASE, HTTP_X_FORWARDED_HOST="example.invalid").status_code, 403)
        contract = self.client.get(BASE + "schema.json").json()
        self.assertTrue(contract["read_only"])
        self.assertEqual(contract["methods"], ["GET", "HEAD"])
        self.assertEqual(LibraryVersion.objects.count(), 0)

    def test_native_allowed_search_stable_references_and_bounded_pagination(self):
        first = self.source()
        second = self.release(self.write(payload=payload(title="أصل آخر اصطناعي")), uses=["PUBLIC_METADATA"])
        hidden = self.write(payload=payload(title="سر خاص غير منشور"))
        before = list(LibraryVersion.objects.order_by("id").values())
        result = self.client.get(BASE, {"limit": 1}).json()
        self.assertEqual(result["pagination"]["total"], 2)
        self.assertEqual(len(result["results"]), 1)
        following = self.client.get(result["pagination"]["next"]).json()
        self.assertEqual({result["results"][0]["material_id"], following["results"][0]["material_id"]}, {first["public_id"], second["public_id"]})
        found = self.client.get(BASE, {"q": "قراءة", "kind": "BOOK"}).json()["results"]
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["version_sha256"], first["digest"])
        self.assertEqual(row["reference"]["locator"], first["payload"]["source_locator"])
        self.assertEqual(row["reference"]["canonical_url"], f"/library-preview/materials/{first['public_id']}/1/")
        self.assertNotIn("private-source-name", str(row))
        for secret in (self.receipt["case_id"], self.receipt["public_ref"], first["version_id"], hidden["version_id"], "rights_basis", "storage_key"):
            self.assertNotIn(secret, str(row))
        self.assertEqual(list(LibraryVersion.objects.order_by("id").values()), before)

    def test_bad_duplicate_unbounded_and_private_filters_are_rejected(self):
        for query in ("q=a&q=b", "case_id=1", "version_id=1", "page=0", "page=1001", "limit=21", "limit=true", "page=١", "kind=PRIVATE", "q=" + "a" * 121, "q=%00"):
            with self.subTest(query=query):
                response = self.client.get(BASE + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_metadata_permission_cannot_expose_content_or_original(self):
        row = self.source(uses=["PUBLIC_METADATA"])
        response = self.client.get(self.url(row)).json()["material"]
        self.assertEqual(response["recorded_text"], "")
        self.assertIsNone(response["file"])
        self.assertIsNone(response["links"]["original"])
        self.assertEqual(self.client.get(self.url(row) + "original/").status_code, 404)

    def test_actual_original_bytes_and_head_use_fresh_authority(self):
        row = self.source()
        url = self.url(row) + "original/"
        result = self.client.get(url)
        self.assertEqual(result.content, TEXT)
        self.assertEqual(result["X-Content-SHA256"], sha256(TEXT).hexdigest())
        self.assertNotIn("private-source-name", result["Content-Disposition"])
        self.assertIn("no-store", result["Cache-Control"])
        self.assertEqual(self.client.head(url).content, b"")
        self.authority.denied.add("DOWNLOAD")
        self.assertEqual(self.client.head(url).status_code, 404)
        self.assertIsNone(self.client.get(self.url(row)).json()["material"]["links"]["original"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_exact_history_never_silently_substitutes_latest_version(self):
        first = self.source()
        second = self.write(namespace=first["namespace"], external_id=first["external_id"], expected_version=1,
                            payload=payload(title="مراجعة جديدة منفصلة", edition_label="الإصدار الثاني"))
        self.assertEqual(self.client.get(BASE).json()["results"][0]["version"], 1)
        second = self.release(second)
        self.assertEqual(self.client.get(BASE).json()["results"][0]["version"], 2)
        self.assertEqual(self.client.get(self.url(first)).json()["material"]["version_sha256"], first["digest"])
        self.decide(first, "WITHDRAW")
        self.assertEqual(self.client.get(self.url(first)).status_code, 404)
        self.assertEqual(self.client.get(self.url(second)).json()["material"]["version"], 2)
        self.assertEqual(LibraryVersion.objects.count(), 2)

    def test_missing_identity_authority_and_revoked_release_deny_existing_urls(self):
        row = self.source()
        for key in ("FATWA_CASEWORK_IDENTITY_PROVIDER", "FATWA_RESEARCH_LIBRARY_AUTHORITY"):
            with self.subTest(key=key), override_settings(**{key: None}):
                self.assertEqual(self.client.get(self.url(row)).status_code, 404)
        old = self.directory.identities["publisher"]
        self.directory.identities["publisher"] = replace(old, active=False)
        self.assertEqual(self.client.get(self.url(row)).status_code, 404)
        self.directory.identities["publisher"] = old
        self.assertEqual(self.client.get(self.url(row)).status_code, 200)
        self.authority.denied.add("RELEASE")
        self.assertEqual(self.client.get(BASE).json()["pagination"]["total"], 0)
        self.assertEqual(self.client.get(self.url(row)).status_code, 404)

    def test_expired_source_rechecks_before_json_and_download(self):
        row = self.source()
        future = timezone.now() + timedelta(hours=1)
        with patch("django.utils.timezone.now", return_value=future):
            self.assertEqual(self.client.get(self.url(row)).status_code, 404)
            self.assertEqual(self.client.get(self.url(row) + "original/").status_code, 404)

    def test_late_serialization_policy_withdrawal_discards_material_response(self):
        row = self.source()
        original = views.JsonResponse
        def late(*args, **kwargs):
            response = original(*args, **kwargs)
            if "material" in args[0]:
                self.authority.denied.add("RELEASE")
            return response
        with patch.object(views, "JsonResponse", side_effect=late):
            response = self.client.get(self.url(row))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(row["payload"]["title"].encode(), response.content)

    def test_real_storage_callback_revokes_identity_after_serialization(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(prefix="api-source-"))
        storage = ReadCallbackStorage(Path(folder) / "private", synthetic_fixtures_only=True)
        self.enterContext(override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage))
        row = self.source()
        before = list(LibraryDecision.objects.order_by("id").values())
        original = views.JsonResponse
        def late(*args, **kwargs):
            response = original(*args, **kwargs)
            if "material" in args[0]:
                storage.hook = lambda: self.directory.identities.update(publisher=replace(self.directory.identities["publisher"], active=False))
            return response
        with patch.object(views, "JsonResponse", side_effect=late):
            response = self.client.get(self.url(row))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(TEXT, response.content)
        self.assertEqual(list(LibraryDecision.objects.order_by("id").values()), before)

    def test_flag_mutation_during_render_is_not_literal_true(self):
        row = self.source()
        original = views.JsonResponse
        changed = override_settings(FATWA_MATERIAL_API_ENABLED=1)
        def late(*args, **kwargs):
            response = original(*args, **kwargs)
            if "material" in args[0]:
                changed.enable()
            return response
        try:
            with patch.object(views, "JsonResponse", side_effect=late):
                response = self.client.get(self.url(row))
            self.assertEqual(response.status_code, 404)
        finally:
            changed.disable()

    def test_developer_navigation_and_schema_match_real_route_fields(self):
        row = self.source()
        index = self.client.get("/library-preview/materials/")
        self.assertContains(index, "واجهة المواد للمطورين")
        docs = self.client.get(BASE + "docs/", {"q": "قراءة"})
        self.assertContains(docs, self.url(row))
        self.assertContains(docs, "فتح نتيجة JSON")
        contract = self.client.get(BASE + "schema.json").json()
        actual = self.client.get(self.url(row)).json()["material"]
        self.assertEqual(set(actual), set(contract["material_fields"]))
        self.assertEqual(set(actual["file"]), set(contract["file_fields"]))
        self.assertEqual(library.KINDS, {"BOOK", "DOCUMENT", "IMAGE", "AUDIO", "VIDEO"})
