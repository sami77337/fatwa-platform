"""Native exact FT opening, explicit disclosure, source withdrawal and final trust."""

import uuid
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import CaseEvent
from apps.experimental_publication import services as publication
from apps.experimental_publication.tests import Directory
from apps.public_answer_media.boundaries import core_state
from apps.public_answer_media.test_support import CREDENTIALS
from apps.research_library.test_support import bind_identity_snapshot
from tests.casework.test_http import post

from . import views
from .reference_test_support import FEATURES, ReferenceFixture


@override_settings(**FEATURES)
class FatwaReferenceTests(ReferenceFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def test_native_exact_public_open_displays_number_and_only_published_text(self):
        before = core_state(self.receipt["case_id"])
        index = self.client.get("/library-preview/")
        self.assertContains(index, 'id="public-reference-lookup"')
        for url in (self.reference_url, self.detail_url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertContains(response, 'id="published-fatwa-reference"')
            self.assertContains(response, self.receipt["public_ref"])
            self.assertContains(response, self.publication.body)
            for private in ("PRIVATE", self.receipt["case_id"], self.receipt["token"]):
                self.assertNotContains(response, private)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(self.client.head(url).content, b"")
        self.assertEqual(core_state(self.receipt["case_id"]), before)

    def test_direct_staff_form_reuses_real_auth_csrf_and_exact_current_scope(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        accepted = post(
            client, "/casework/staff/login/", {"credential": CREDENTIALS["editor"]}, login
        )
        self.assertEqual(accepted.status_code, 303)
        page = client.get("/casework/staff/")
        self.assertContains(page, 'id="staff-reference-lookup"')
        before = CaseEvent.objects.count()
        opened = post(
            client,
            "/casework/staff/",
            {"action": "open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(opened.status_code, 200, opened.content)
        self.assertContains(opened, self.receipt["public_ref"])
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertEqual(
            client.post(
                "/casework/staff/", {"action": "open", "case_ref": self.receipt["public_ref"]}
            ).status_code,
            403,
        )
        key = uuid.uuid4().hex
        other = cases.intake_case(
            original_question="PRIVATE other exact case",
            source_event_id=key,
            requester_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        denied = []
        for ref in (other["public_ref"], "FT-2026-" + "A" * 20):
            response = post(client, "/casework/staff/", {"action": "open", "case_ref": ref}, page)
            self.assertEqual(response.status_code, 403)
            self.assertNotContains(response, ref, status_code=403)
            self.assertNotContains(response, "PRIVATE", status_code=403)
            denied.append(response.content)
        self.assertEqual(*denied)
        old = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(old, active=False)
        self.assertEqual(
            post(
                client,
                "/casework/staff/",
                {"action": "open", "case_ref": self.receipt["public_ref"]},
                page,
            ).status_code,
            403,
        )

    def test_private_missing_malformed_and_ungranted_references_are_indistinguishable(self):
        key = uuid.uuid4().hex
        private = cases.intake_case(
            original_question="PRIVATE not published",
            source_event_id=key,
            requester_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        bodies = []
        for ref in (
            private["public_ref"],
            "FT-2026-" + "0" * 20,
            self.receipt["public_ref"][:-1],
            self.receipt["public_ref"].lower(),
            "عنوان مشابه",
        ):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get("/library-preview/by-reference/", {"ref": ref})
            self.assertEqual(response.status_code, 404, response.content)
            self.assertNotIn(ref.encode(), response.content)
            self.assertFalse(
                any('FROM "casework_case"' in row["sql"] for row in queries),
                "unknown public reference must not scan private cases",
            )
            bodies.append(response.content)
        self.assertEqual(len(set(bodies)), 1)
        for query in ("", "?ref=x&ref=y", "?ref=x&role=MUFTI"):
            self.assertEqual(
                self.client.get("/library-preview/by-reference/" + query).status_code, 400
            )
        self.assertEqual(
            self.client.post(
                "/library-preview/by-reference/", {"ref": self.receipt["public_ref"]}
            ).status_code,
            405,
        )

    def test_publication_read_permission_never_infers_reference_disclosure(self):
        for flags in (
            {"FATWA_REFERENCE_LOOKUP_ENABLED": False},
            {"FATWA_REFERENCE_LOOKUP_ENABLED": "1"},
            {"FATWA_PUBLIC_FATWA_REFERENCES": None},
            {"FATWA_PUBLIC_FATWA_REFERENCES": replace(self.reference_policy, grants=())},
        ):
            with override_settings(**flags):
                self.assertEqual(self.client.get(self.reference_url).status_code, 404)
                page = self.client.get(self.detail_url)
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, self.receipt["public_ref"])

    def test_grant_must_bind_exact_edition_reference_hash_and_current_publishing_actor(self):
        replacements = (
            {"publication_id": str(uuid.uuid4())},
            {"content_sha256": "0" * 64},
            {"reference": "FT-2026-" + "B" * 20},
            {"provider_id": "other-provider"},
            {"subject_id": "editor"},
            {"auth_epoch": "other-epoch"},
        )
        for values in replacements:
            with (
                self.subTest(values=values),
                override_settings(
                    FATWA_PUBLIC_FATWA_REFERENCES=replace(
                        self.reference_policy, grants=(replace(self.reference_grant, **values),)
                    )
                ),
            ):
                self.assertEqual(self.client.get(self.reference_url).status_code, 404)
        for changes in (
            {"FATWA_CASEWORK_IDENTITY_PROVIDER": None},
            {"FATWA_LIBRARY_PREVIEW_POLICY": None},
            {"FATWA_SOURCE_RIGHTS_AUTHORITY": None},
        ):
            with override_settings(**changes):
                self.assertEqual(self.client.get(self.reference_url).status_code, 404)
        current = self.directory.identities["publisher"]
        self.directory.identities["publisher"] = replace(current, active=False)
        self.assertEqual(self.client.get(self.reference_url).status_code, 404)
        self.directory.identities["publisher"] = current
        self.assertEqual(self.client.get(self.reference_url).status_code, 200)

    def test_expired_duplicate_unbounded_and_malformed_disclosure_configuration_rejects(self):
        invalid = (
            replace(self.reference_policy, valid_until=timezone.now() - timedelta(seconds=1)),
            replace(self.reference_policy, valid_until=timezone.now() + timedelta(hours=2)),
            replace(self.reference_policy, synthetic_fixtures_only=False),
            replace(self.reference_policy, grants=list(self.reference_policy.grants)),
            replace(self.reference_policy, grants=(self.reference_grant, self.reference_grant)),
            replace(self.reference_policy, grants=(self.reference_grant,) * 65),
            replace(
                self.reference_policy, grants=(replace(self.reference_grant, publication_id="bad"),)
            ),
        )
        for selected in invalid:
            with (
                self.subTest(selected=selected),
                override_settings(FATWA_PUBLIC_FATWA_REFERENCES=selected),
            ):
                self.assertEqual(self.client.get(self.reference_url).status_code, 404)

    def test_withdrawal_and_superseding_edition_do_not_fall_back_to_old_reference(self):
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=self.edition["id"],
            action="WITHDRAW",
        )
        self.assertEqual(self.client.get(self.reference_url).status_code, 404)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)

    def test_new_approved_edition_requires_a_new_exact_disclosure_grant(self):
        newer = publication.create_edition(
            **self.common,
            title="تصحيح مستقل",
            category="موضوع",
            body="نص عام مصحح",
            expected_revision=3,
            expected_evidence_version=1,
        )
        publication.act(
            **{**self.common, "subject_id": "other"},
            edition_id=newer["id"],
            action="REVIEW",
            reviewed=True,
        )
        publication.act(
            **{**self.common, "subject_id": "publisher"}, edition_id=newer["id"], action="APPROVE"
        )
        self.assertEqual(self.client.get(self.reference_url).status_code, 404)

    def test_equal_policy_object_swap_during_render_discards_reference_and_body(self):
        original = views.render

        def replace_policy(*args, **kwargs):
            response = original(*args, **kwargs)
            settings.FATWA_PUBLIC_FATWA_REFERENCES = replace(self.reference_policy)
            return response

        with (
            override_settings(FATWA_PUBLIC_FATWA_REFERENCES=self.reference_policy),
            patch.object(views, "render", side_effect=replace_policy),
        ):
            response = self.client.get(self.reference_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.publication.body, status_code=404)
        self.assertNotContains(response, self.receipt["public_ref"], status_code=404)

    def test_equal_epoch_directory_swap_during_render_is_denied(self):
        alternate = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        alternate.identities = self.directory.identities.copy()
        self.assertEqual(alternate.projection_epoch(), self.directory.projection_epoch())
        original = views.render

        def replace_directory(*args, **kwargs):
            response = original(*args, **kwargs)
            settings.FATWA_CASEWORK_IDENTITY_PROVIDER = alternate
            return response

        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory),
            patch.object(views, "render", side_effect=replace_directory),
        ):
            response = self.client.get(self.reference_url)
        self.assertEqual(response.status_code, 404)

    def test_late_render_source_withdrawal_rolls_back_and_denies_stale_response(self):
        before = core_state(self.receipt["case_id"])
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            publication.act(
                **{**self.common, "subject_id": "publisher"},
                edition_id=self.edition["id"],
                action="WITHDRAW",
            )
            return response

        with patch.object(views, "render", side_effect=withdraw):
            response = self.client.get(self.reference_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.publication.body, status_code=404)
        self.assertEqual(core_state(self.receipt["case_id"]), before)

    def test_late_actor_revocation_discards_rendered_public_number(self):
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            actor = self.directory.identities["publisher"]
            self.directory.identities["publisher"] = replace(actor, active=False)
            return response

        with patch.object(views, "render", side_effect=revoke):
            response = self.client.get(self.reference_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.receipt["public_ref"], status_code=404)
