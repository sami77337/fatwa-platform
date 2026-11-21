"""Real PostgreSQL curation, independent decisions, privacy and anonymous rendering."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from xml.etree import ElementTree

from django.db import IntegrityError, connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.library_preview.tests import ENABLED, PreviewFixture
from tests.casework.test_http import WEB_SETTINGS, post

from . import editor, services, views
from .authority import PublicKnowledgeAuthority
from .models import PublicAction, PublicRevision, PublicSeries

FEATURES = {
    **WEB_SETTINGS,
    **ENABLED,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_PUBLIC_KNOWLEDGE_ENABLED": True,
    "FATWA_PUBLIC_KNOWLEDGE_LANGUAGES": {"ar": "العربية", "en": "English"},
    "FATWA_PUBLIC_KNOWLEDGE_ORIGIN": "https://preview.example.test",
    "MIDDLEWARE": [
        "apps.library_preview.guard.PreviewCompositionGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


class FixtureAuthority(PublicKnowledgeAuthority):
    def __init__(self, ref, *, provider_id="synthetic-publication-directory"):
        self.ref, self.denied = ref, set()
        self.provider_id = provider_id

    def projection_epoch(self):
        return repr((self.provider_id, self.ref, sorted(self.denied)))

    def permits(self, **values):
        return (
            values["provider_id"] == self.provider_id
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == self.ref
            and values["action"] in {"EDIT", "READ", "REVIEW", "APPROVE", "RELEASE", "WITHDRAW"}
            and values["kind"] in services.KINDS
            and (values["action"], values["kind"]) not in self.denied
        )


class CurationFixture(PreviewFixture):
    def setUp(self):
        super().setUp()
        self.curation_authority = FixtureAuthority(
            self.receipt["public_ref"], provider_id=self.directory.provider_id
        )
        configured = override_settings(
            FATWA_PUBLIC_KNOWLEDGE_AUTHORITY=self.curation_authority,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.directory.authenticate = lambda credential: self.directory.resolve(
            {
                "synthetic-editor-credential-32-characters": "editor",
                "synthetic-reviewer-credential-32-characters": "other",
                "synthetic-publisher-credential-32-characters": "publisher",
            }.get(credential, "")
        )

    def save_record(self, kind="SCHOLAR", **changes):
        defaults = {
            "SCHOLAR": {"name": "عالم تجريبي", "bio": ""},
            "TOPIC": {
                "title": "موضوع السفر التجريبي",
                "introduction": "مقدمة تحريرية اصطناعية",
                "parent_id": "",
            },
            "PRESENTATION": {
                "title": "عنوان تجريبي",
                "question": "صيغة سؤال عامة اصطناعية",
                "body": "",
                "description": "وصف مصرح به",
                "scholar_id": "",
                "topic_ids": [],
                "relation_ids": [],
            },
        }
        arguments = dict(
            self.common,
            publication_id=self.edition["id"],
            kind=kind,
            language="ar" if kind == "PRESENTATION" else "",
            expected_version=0,
            expected_revision=4,
            expected_evidence_version=2,
            payload=defaults[kind],
            request_key=str(uuid.uuid4()),
        )
        return services.save(**{**arguments, **changes})

    def decision(self, record, action, **changes):
        arguments = dict(
            self.common,
            subject_id="other" if action == "REVIEW" else "publisher",
            revision_id=record["id"],
            expected_actions=record["action_count"],
            expected_revision=4,
            expected_evidence_version=2,
            action=action,
            request_key=str(uuid.uuid4()),
            note="مراجعة بشرية اصطناعية للنسبة والمعنى والخصوصية",
            minutes=15 if action == "RELEASE" else 0,
            related_id=record["lease_id"] if action == "REVOKE" else "",
            confirmed=True,
        )
        return services.act(**{**arguments, **changes})

    def approve_record(self, record):
        return self.decision(self.decision(record, "REVIEW"), "APPROVE")

    def release_record(self, record):
        return self.decision(self.approve_record(record), "RELEASE")

    def published(self):
        scholar = self.release_record(self.save_record())
        parent = self.release_record(self.save_record("TOPIC"))
        child = self.release_record(
            self.save_record(
                "TOPIC",
                payload={"title": "فرع بحثي", "introduction": "", "parent_id": parent["id"]},
            )
        )
        presentation = self.release_record(
            self.save_record(
                "PRESENTATION",
                payload={
                    "title": "عنوان تجريبي",
                    "question": "سؤال عام محرر",
                    "body": "",
                    "description": "وصف عام",
                    "scholar_id": scholar["id"],
                    "topic_ids": [child["id"]],
                    "relation_ids": [],
                },
            )
        )
        translation = self.release_record(
            self.save_record(
                "PRESENTATION",
                language="en",
                payload={
                    "title": "Synthetic reviewed title",
                    "question": "Synthetic public question",
                    "body": "Reviewed synthetic translation, not a religious ruling.",
                    "description": "Reviewed synthetic metadata",
                    "scholar_id": scholar["id"],
                    "topic_ids": [child["id"]],
                    "relation_ids": [],
                },
            )
        )
        return scholar, parent, child, presentation, translation

    def page(self, record, kind="scholars"):
        return self.client.get(f"/library-preview/knowledge/{kind}/{record['series_id']}/")

    def staff_client(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        credential = {
            "editor": "synthetic-editor-credential-32-characters",
            "other": "synthetic-reviewer-credential-32-characters",
            "publisher": "synthetic-publisher-credential-32-characters",
        }[subject]
        result = post(client, "/casework/staff/login/", {"credential": credential}, login)
        self.assertEqual(result.status_code, 303, result.content)
        return client, client.get("/casework/staff/")


@override_settings(**FEATURES)
class PublicKnowledgeTests(CurationFixture, TransactionTestCase):
    def test_profiles_hubs_translations_and_structured_navigation_preserve_sources(self):
        originals = (
            list(AnswerRevision.objects.values()),
            list(CaseEvent.objects.values()),
            list(PublicationEdition.objects.values()),
        )
        scholar, parent, child, presentation, translation = self.published()
        response = self.page(scholar)
        self.assertContains(response, "عالم تجريبي")
        self.assertContains(response, "عنوان تجريبي")
        self.assertContains(response, "https://schema.org/Person")
        self.assertNotContains(response, "متوسط زمن")
        for target in (parent, child):
            response = self.page(target, "topics")
            self.assertContains(response, "عنوان تجريبي")
            self.assertContains(response, "https://schema.org/BreadcrumbList")
            self.assertContains(response, "https://schema.org/CollectionPage")
        url = f"/library-preview/knowledge/publications/{self.edition['id']}/en/"
        response = self.client.get(url)
        self.assertContains(response, translation["payload"]["body"])
        self.assertContains(response, 'itemprop="translationOfWork"')
        self.assertContains(response, 'itemprop="inLanguage" content="en"')
        self.assertContains(response, "فتح الأصل العربي المحفوظ")
        self.assertEqual(response.cookies, {})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("noindex", response["X-Robots-Tag"])
        for secret in (
            "PRIVATE",
            self.receipt["public_ref"],
            self.receipt["case_id"],
            "synthetic-publication-directory",
            "epoch-1",
            self.transcript_source_id,
        ):
            self.assertNotContains(response, secret)
        self.assertEqual(
            originals,
            (
                list(AnswerRevision.objects.values()),
                list(CaseEvent.objects.values()),
                list(PublicationEdition.objects.values()),
            ),
        )

    def test_approval_alone_cannot_release_profile_or_unreviewed_translation(self):
        scholar = self.save_record()
        self.assertEqual(self.page(scholar).status_code, 404)
        with self.assertRaises(cases.CaseConflict):
            self.decision(scholar, "REVIEW", subject_id="editor")
        with self.assertRaises(cases.CaseConflict):
            self.decision(scholar, "APPROVE")
        scholar = self.approve_record(scholar)
        self.assertEqual(self.page(scholar).status_code, 404)
        scholar = self.decision(scholar, "RELEASE")
        self.assertEqual(self.page(scholar).status_code, 200)
        response = self.client.get(
            f"/library-preview/knowledge/publications/{self.edition['id']}/en/"
        )
        self.assertContains(response, "لا توجد ترجمة مراجعة")
        self.assertContains(response, "نص محرر مسموح")
        self.assertContains(response, 'itemprop="inLanguage" content="ar"')

    def test_exact_source_grant_required_separately_from_curation_release(self):
        scholar = self.approve_record(self.save_record())
        with override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=replace(self.preview_policy, publications=())
        ):
            with self.assertRaises(preview.PreviewUnavailable):
                self.decision(scholar, "RELEASE")
        self.assertEqual(PublicAction.objects.filter(action="RELEASE").count(), 0)
        scholar = self.decision(scholar, "RELEASE")
        with override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=replace(self.preview_policy, publications=())
        ):
            self.assertEqual(self.page(scholar).status_code, 404)

    def test_lease_revoke_expiry_and_source_withdrawal_close_views_and_sitemap(self):
        scholar = self.release_record(self.save_record())
        self.assertEqual(self.page(scholar).status_code, 200)
        future = scholar["lease_until"] + timedelta(seconds=1)
        with patch("django.utils.timezone.now", return_value=future):
            self.assertEqual(self.page(scholar).status_code, 404)
        scholar = self.decision(scholar, "REVOKE")
        self.assertEqual(self.page(scholar).status_code, 404)
        scholar = self.decision(scholar, "RELEASE")
        self.assertEqual(self.page(scholar).status_code, 200)
        self.withdraw()
        self.assertEqual(self.page(scholar).status_code, 404)
        xml = self.client.get("/library-preview/knowledge/sitemap.xml")
        self.assertNotIn(scholar["series_id"].encode(), xml.content)
        self.assertNotIn(self.edition["id"].encode(), xml.content)

    def test_current_release_identity_and_kind_authority_are_not_cached(self):
        scholar = self.release_record(self.save_record())
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], auth_epoch="revoked"
        )
        self.assertEqual(self.page(scholar).status_code, 404)
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], auth_epoch="epoch-1"
        )
        self.curation_authority.denied.add(("RELEASE", "SCHOLAR"))
        self.assertEqual(self.page(scholar).status_code, 404)

    def test_mid_render_revocation_discards_complete_generated_html(self):
        scholar = self.release_record(self.save_record())
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.curation_authority.denied.add(("RELEASE", "SCHOLAR"))
            return response

        with patch.object(views, "render", side_effect=revoke):
            response = self.page(scholar)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("عالم تجريبي".encode(), response.content)

    def test_value_equal_replacement_public_authority_cannot_survive_render(self):
        from django.conf import settings

        class EqualAuthority(FixtureAuthority):
            def __eq__(self, other):
                return True

        scholar = self.release_record(self.save_record())
        original = views.render

        def replace_policy(*args, **kwargs):
            response = original(*args, **kwargs)
            settings.FATWA_PUBLIC_KNOWLEDGE_AUTHORITY = EqualAuthority(self.receipt["public_ref"])
            return response

        with (
            override_settings(FATWA_PUBLIC_KNOWLEDGE_AUTHORITY=self.curation_authority),
            patch.object(views, "render", side_effect=replace_policy),
        ):
            response = self.page(scholar)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "عالم تجريبي", status_code=404)

    def test_late_source_withdrawal_rolls_back_the_curation_command(self):
        original = self.curation_authority.permits
        edits = 0

        def withdraw(**kwargs):
            nonlocal edits
            if kwargs["action"] == "EDIT":
                edits += 1
                if edits == 2:
                    self.withdraw()
            return original(**kwargs)

        with patch.object(self.curation_authority, "permits", side_effect=withdraw):
            with self.assertRaises(cases.CaseConflict):
                self.save_record()
        self.assertEqual(PublicRevision.objects.count(), 0)
        self.assertEqual(PublicSeries.objects.count(), 0)
        self.assertEqual(preview.browse()["total"], 1)

    def test_concurrent_revision_writers_have_one_winner_and_original_history(self):
        record = self.save_record()

        def save(number):
            connections.close_all()
            try:
                try:
                    return self.save_record(
                        series_id=record["series_id"],
                        expected_version=1,
                        payload={"name": f"اسم {number}", "bio": ""},
                    )["number"]
                except cases.CaseConflict:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (1, 2)))
        self.assertCountEqual(results, [2, "conflict"])
        self.assertEqual(PublicRevision.objects.count(), 2)
        previous = services.read_revision(**self.common, revision_id=record["id"])
        self.assertFalse(previous["current"])
        self.assertEqual(previous["payload"]["name"], "عالم تجريبي")

    def test_exact_retries_are_idempotent_but_changed_payload_or_duration_conflicts(self):
        key = str(uuid.uuid4())
        record = self.save_record(request_key=key)
        self.assertEqual(self.save_record(request_key=key)["id"], record["id"])
        with self.assertRaises(cases.CaseConflict):
            self.save_record(request_key=key, payload={"name": "تغيير", "bio": ""})
        record = self.approve_record(record)
        key = str(uuid.uuid4())
        released = self.decision(record, "RELEASE", request_key=key, minutes=5)
        self.assertEqual(
            self.decision(record, "RELEASE", request_key=key, minutes=5)["lease_id"],
            released["lease_id"],
        )
        with self.assertRaises(cases.CaseConflict):
            self.decision(record, "RELEASE", request_key=key, minutes=30)

    def test_new_topic_revision_does_not_silently_rebind_child_or_translation(self):
        scholar, parent, child, presentation, translation = self.published()
        self.save_record(
            "TOPIC",
            series_id=parent["series_id"],
            expected_version=1,
            payload={"title": "موضوع معدل غير معتمد", "introduction": "", "parent_id": ""},
        )
        self.assertEqual(self.page(parent, "topics").status_code, 404)
        self.assertEqual(self.page(child, "topics").status_code, 404)
        response = self.client.get(
            f"/library-preview/knowledge/publications/{self.edition['id']}/en/"
        )
        self.assertContains(response, "لا توجد ترجمة مراجعة")
        self.assertNotContains(response, translation["payload"]["body"])

    def test_translation_revisions_preserve_old_text_and_need_fresh_review_and_release(self):
        _, _, _, _, first = self.published()
        original = PublicationEdition.objects.get(pk=self.edition["id"])
        before = (original.body, original.content_sha256)
        second = self.save_record(
            "PRESENTATION",
            language="en",
            series_id=first["series_id"],
            expected_version=1,
            payload={**first["payload"], "body": "Second human translation revision."},
        )
        self.assertEqual(second["number"], 2)
        url = f"/library-preview/knowledge/publications/{self.edition['id']}/en/"
        draft = self.client.get(url)
        self.assertContains(draft, "لا توجد ترجمة مراجعة")
        self.assertNotContains(draft, first["payload"]["body"])
        self.assertNotContains(draft, second["payload"]["body"])
        historical = services.read_revision(**self.common, revision_id=first["id"])
        self.assertFalse(historical["current"])
        self.assertEqual(
            (historical["payload"], historical["sha256"]), (first["payload"], first["sha256"])
        )
        approved = self.approve_record(second)
        self.assertNotContains(self.client.get(url), second["payload"]["body"])
        released = self.decision(approved, "RELEASE")
        page = self.client.get(url)
        self.assertContains(page, second["payload"]["body"])
        self.assertContains(page, 'itemprop="version" content="2"')
        self.assertNotContains(page, first["payload"]["body"])
        self.decision(released, "WITHDRAW")
        self.assertNotContains(self.client.get(url), second["payload"]["body"])
        original.refresh_from_db()
        self.assertEqual((original.body, original.content_sha256), before)

    def test_source_configuration_revoked_during_render_discards_html(self):
        from django.conf import settings

        scholar = self.release_record(self.save_record())
        original = views.render

        def disable(*args, **kwargs):
            response = original(*args, **kwargs)
            settings.FATWA_EXPERIMENTAL_PUBLICATION_ENABLED = False
            return response

        with (
            override_settings(FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True),
            patch.object(views, "render", side_effect=disable),
        ):
            response = self.page(scholar)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "عالم تجريبي", status_code=404)

    def test_database_rejects_changes_and_independent_approval_bypass(self):
        record = self.save_record()
        for mutate in (
            lambda: PublicRevision.objects.filter(pk=record["id"]).update(payload={}),
            lambda: PublicSeries.objects.filter(pk=record["series_id"]).update(
                author_subject="publisher"
            ),
            lambda: PublicRevision.objects.filter(pk=record["id"]).delete(),
            lambda: PublicAction.objects.create(
                revision_id=record["id"],
                sequence=1,
                action="APPROVE",
                request_key=uuid.uuid4(),
                content_sha256=record["sha256"],
                note="bypass",
                provider_id=self.directory.provider_id,
                subject_id="publisher",
                auth_epoch="epoch-1",
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                mutate()
        record = self.release_record(record)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PublicAction.objects.filter(revision_id=record["id"]).update(note="changed")

    def test_sitemap_contains_only_current_released_urls_and_sanitized_origin(self):
        scholar, parent, child, presentation, translation = self.published()
        response = self.client.get("/library-preview/knowledge/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        document = ElementTree.fromstring(response.content)
        urls = [node.text for node in document.findall("{*}url/{*}loc")]
        self.assertTrue(any("/en/" in url for url in urls))
        self.assertTrue(
            all(
                url.startswith("https://preview.example.test/library-preview/knowledge/")
                for url in urls
            )
        )
        self.assertFalse(any("casework" in url or "?" in url for url in urls))
        self.decision(translation, "REVOKE")
        response = self.client.get("/library-preview/knowledge/sitemap.xml")
        self.assertNotIn(b"/en/", response.content)
        with override_settings(FATWA_PUBLIC_KNOWLEDGE_ORIGIN="https://user:password@example.test/"):
            self.assertEqual(
                self.client.get("/library-preview/knowledge/sitemap.xml").status_code, 404
            )

    def test_default_off_missing_versioned_policy_and_invalid_inputs_do_not_write(self):
        with (
            override_settings(FATWA_PUBLIC_KNOWLEDGE_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.save_record()
        with (
            patch.object(self.curation_authority, "projection_epoch", return_value=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.save_record()
        for payload in (
            {"name": "", "bio": ""},
            {"name": "x" * 161, "bio": ""},
            {"name": "x", "bio": "", "actor": "publisher"},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.save_record(payload=payload)
        with self.assertRaises(cases.CaseConflict):
            self.save_record(
                "PRESENTATION",
                payload={
                    "title": "عنوان تجريبي",
                    "question": "",
                    "body": "changed Arabic",
                    "description": "",
                    "scholar_id": "",
                    "topic_ids": [],
                    "relation_ids": [],
                },
            )
        self.assertEqual(PublicRevision.objects.count(), 0)

    def test_native_editor_discards_rendered_history_when_a_decision_changes_during_render(self):
        record = self.release_record(self.save_record())
        client, state = self.staff_client()
        original = editor.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.decision(record, "WITHDRAW")
            return response

        before = PublicAction.objects.count()
        with patch.object(editor, "render", side_effect=withdraw):
            response = post(
                client,
                "/casework/staff/",
                {"action": "pk_open", "case_ref": self.receipt["public_ref"]},
                state,
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, "عالم تجريبي", status_code=409)
        self.assertEqual(PublicAction.objects.count(), before)

    def test_selected_revision_is_read_inside_the_same_native_history_boundary(self):
        record = self.release_record(self.save_record())
        client, state = self.staff_client()
        original = services.read_revision

        def withdraw_after_read(**kwargs):
            selected = original(**kwargs)
            self.decision(record, "WITHDRAW")
            return selected

        before = PublicAction.objects.count()
        with patch.object(services, "read_revision", side_effect=withdraw_after_read):
            response = post(
                client,
                "/casework/staff/",
                {
                    "action": "pk_revision",
                    "case_ref": self.receipt["public_ref"],
                    "revision_id": record["id"],
                },
                state,
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, "عالم تجريبي", status_code=409)
        self.assertEqual(PublicAction.objects.count(), before)

    def test_native_csrf_forms_create_review_release_and_read_real_profile(self):
        client, page = self.staff_client()
        opened = post(
            client,
            "/casework/staff/",
            {"action": "pk_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(opened.status_code, 200, opened.content)
        fields = {
            "action": "pk_save_scholar",
            "case_ref": self.receipt["public_ref"],
            "revision": "4",
            "evidence_version": "2",
            "publication_id": self.edition["id"],
            "series_id": "",
            "expected_version": "0",
            "request_key": str(uuid.uuid4()),
            "name": "اسم <script>escaped</script>",
            "bio": "",
        }
        rejected = client.post("/casework/staff/", fields)
        self.assertEqual(rejected.status_code, 403)
        saved = post(client, "/casework/staff/", fields, opened)
        self.assertEqual(saved.status_code, 200, saved.content)
        record = saved.context["result"]["records"][0]
        self.assertContains(saved, "&lt;script&gt;escaped&lt;/script&gt;")
        for actor, action in (
            ("other", "REVIEW"),
            ("publisher", "APPROVE"),
            ("publisher", "RELEASE"),
        ):
            browser, state = self.staff_client(actor)
            command = {
                "action": "pk_act",
                "case_ref": self.receipt["public_ref"],
                "revision": "4",
                "evidence_version": "2",
                "revision_id": record["id"],
                "expected_actions": str(record["action_count"]),
                "command": action,
                "request_key": str(uuid.uuid4()),
                "note": "تحقق بشري",
                "minutes": "15" if action == "RELEASE" else "0",
                "related_id": "",
                "confirmed": "yes",
            }
            response = post(browser, "/casework/staff/", command, state)
            self.assertEqual(response.status_code, 200, response.content)
            record = response.context["result"]["records"][0]
        anonymous = self.page(record)
        self.assertEqual(anonymous.status_code, 200)
        self.assertContains(anonymous, "&lt;script&gt;escaped&lt;/script&gt;")
        self.assertNotContains(anonymous, "<script>")


@override_settings(**FEATURES)
class RecoverySupportTests(TransactionTestCase):
    def test_nonempty_inventory_reconstructs_only_explicit_synthetic_authority(self):
        import json

        from . import recovery_support

        pins = json.loads(json.dumps(recovery_support.populate()))
        proof = recovery_support.verify_restored(pins)
        self.assertEqual(proof["nonempty_tables"], 3)
        self.assertTrue(proof["missing_authority_denied"])
        self.assertTrue(proof["missing_identity_denied"])
