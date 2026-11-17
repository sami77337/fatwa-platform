"""Synthetic canonical fixtures; anonymous preview never gets staff authority."""

import os
import uuid
from dataclasses import replace
from datetime import timedelta
from time import perf_counter
from unittest.mock import patch

from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision
from apps.knowledge_links.tests import FEATURES, Fixture

from . import services
from .policy import PreviewPolicy, PublicationGrant, ReferenceGrant

ENABLED = {**FEATURES, "FATWA_LIBRARY_PREVIEW_ENABLED": True}


class PreviewFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.reference_link = self.propose()
        self.transcript_link = self.propose("TRANSCRIPT")
        self.approve(self.reference_link)
        self.approve(self.transcript_link)
        edition = PublicationEdition.objects.get(pk=self.edition["id"])
        source = edition.citations[0]
        self.grant = PublicationGrant(str(edition.pk), edition.content_sha256)
        self.source_grant = ReferenceGrant(
            source["source"]["edition_id"],
            source["source"]["source_row_id"],
            source["source_sha256"],
        )
        self.preview_policy = PreviewPolicy(
            (self.grant,), (self.source_grant,), timezone.now() + timedelta(minutes=30), True
        )
        self.preview_settings = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.preview_policy)
        self.preview_settings.enable()
        self.addCleanup(self.preview_settings.disable)
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.detail_url = f"/library-preview/editions/{edition.pk}/"
        self.source_url = self.detail_url + "references/1/"

    def candidate(self, **kwargs):
        values = dict(
            self.common,
            expected_revision=4,
            expected_evidence_version=2,
            title="PRIVATE CANDIDATE",
            category="PRIVATE CATEGORY",
            body="PRIVATE DRAFT",
        )
        return publication.create_edition(**{**values, **kwargs})

    def pin(self, *editions, sources=None):
        grants = []
        for edition in editions:
            row = PublicationEdition.objects.get(pk=edition["id"])
            grants.append(PublicationGrant(str(row.pk), row.content_sha256))
        return replace(
            self.preview_policy,
            publications=tuple(grants),
            references=(self.source_grant,) if sources is None else sources,
        )

    def withdraw(self, edition=None):
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=(edition or self.edition)["id"],
            action="WITHDRAW",
        )


@override_settings(**ENABLED)
class PreviewTests(PreviewFixture, TransactionTestCase):
    def test_anonymous_read_only_journey_has_no_private_projection_or_transcript_resolver(self):
        with patch.object(
            knowledge, "_transcripts_locked", side_effect=AssertionError("private read")
        ):
            catalog = services.browse()
            detail = services.read(self.edition["id"])
            source = services.read_reference(self.edition["id"], 1)
            self.assertEqual(catalog["total"], 1)
            self.assertEqual(source["source"]["printed_page"], 2)
            self.assertEqual(len(detail["relations"]["references"]), 1)
            self.assertTrue(detail["relations"]["private_related"])
        data = str((catalog, detail, source))
        for private in (
            "PRIVATE",
            self.receipt["public_ref"],
            self.receipt["case_id"],
            self.transcript_text,
            self.transcript_source_id,
            self.transcript["link_id"],
            "subject_id",
            "auth_epoch",
            "snapshot_sha256",
            "case_id",
            "bundle_sha256",
        ):
            self.assertNotIn(private, data)
        self.assertEqual(set(source["source"]), set(services.SOURCE_FIELDS))

    def test_default_gate_and_expiring_explicit_synthetic_policy(self):
        for settings in (
            {"FATWA_LIBRARY_PREVIEW_ENABLED": False},
            {"FATWA_LIBRARY_PREVIEW_POLICY": None},
            {
                "FATWA_LIBRARY_PREVIEW_POLICY": replace(
                    self.preview_policy, synthetic_fixtures_only=False
                )
            },
            {
                "FATWA_LIBRARY_PREVIEW_POLICY": replace(
                    self.preview_policy, valid_until=timezone.now() - timedelta(seconds=1)
                )
            },
            {
                "FATWA_LIBRARY_PREVIEW_POLICY": replace(
                    self.preview_policy, valid_until=timezone.now() + timedelta(days=1)
                )
            },
            {"FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": False},
        ):
            with override_settings(**settings), self.assertRaises(services.PreviewUnavailable):
                services.browse()
        with (
            patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}),
            self.assertRaises(services.PreviewUnavailable),
        ):
            services.read(self.edition["id"])

    def test_unapproved_candidates_wrong_fingerprint_and_nonlisted_ids_are_invisible(self):
        candidate = self.candidate()
        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.pin(self.edition, candidate)):
            found = services.browse()
            self.assertEqual(found["total"], 1)
            self.assertNotIn("PRIVATE", str(found))
            self.assertEqual(services.browse(query="PRIVATE")["total"], 0)
            for identity in (candidate["id"], str(uuid.uuid4())):
                with self.assertRaises(services.PreviewUnavailable):
                    services.read(identity)
        with override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=replace(
                self.preview_policy, publications=(replace(self.grant, content_sha256="0" * 64),)
            )
        ):
            self.assertEqual(services.browse()["total"], 0)

    def test_reference_rights_required_for_search_display_and_direct_open(self):
        with override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=replace(self.preview_policy, references=())
        ):
            result = services.read(self.edition["id"])
            self.assertEqual(result["references"], [])
            self.assertEqual(result["relations"]["references"], [])
            self.assertEqual(services.browse(query="فرع")["total"], 0)
            self.assertEqual(services.browse(material="reference")["total"], 0)
            with self.assertRaises(services.PreviewUnavailable):
                services.read_reference(self.edition["id"], 1)
        self.assertEqual(services.browse(query="فرع", material="reference")["total"], 1)

    def test_arabic_search_and_categories_only_come_from_visible_editorial_values(self):
        self.candidate()
        self.assertEqual(services.browse(query="عُنْوان", category="تصنيف تجريبي")["total"], 1)
        self.assertEqual(services.browse(category="غير موجود")["total"], 0)
        for query in ("PRIVATE", self.transcript_text, self.transcript_source_id):
            self.assertEqual(services.browse(query=query)["total"], 0)
        self.assertEqual(services.browse()["categories"], ["تصنيف تجريبي"])

    def test_withdrawal_and_new_facts_close_listing_details_and_source(self):
        self.withdraw()
        self.assertEqual(services.browse()["categories"], [])
        self.assertEqual(services.browse()["total"], 0)
        for read in (
            lambda: services.read(self.edition["id"]),
            lambda: services.read_reference(self.edition["id"], 1),
        ):
            with self.assertRaises(services.PreviewUnavailable):
                read()

    def test_new_evidence_invalidates_public_preview_without_exposing_reason(self):
        cases.add_followup(
            token=self.receipt["token"],
            text="PRIVATE NEW FACT",
            expected_revision=4,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(services.browse()["items"], [])
        with self.assertRaises(services.PreviewUnavailable):
            services.read(self.edition["id"])

    def test_corrections_preserve_metadata_history_but_never_old_content_or_candidates(self):
        candidate = self.candidate(
            title="تصحيح آمن", category="تصنيف جديد", body="نص النسخة المصححة"
        )
        publication.act(**self.common, edition_id=candidate["id"], action="REVIEW", reviewed=True)
        # Pending correction does not replace an approved publication.
        self.assertEqual(services.browse()["total"], 1)
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=candidate["id"],
            action="APPROVE",
        )
        # A new approved edition outside the grant hides the old one; no fallback.
        self.assertEqual(services.browse()["total"], 0)
        self.withdraw()
        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.pin(self.edition, candidate)):
            current = services.read(candidate["id"])
            self.assertEqual(current["body"], "نص النسخة المصححة")
            self.assertEqual([r["state"] for r in current["history"]], ["CURRENT", "WITHDRAWN"])
            self.assertEqual(set(current["history"][1]), {"number", "state", "published_at"})
            self.assertEqual(current["relations"]["references"], [])
            with self.assertRaises(services.PreviewUnavailable):
                services.read(self.edition["id"])
            self.withdraw(candidate)
            self.assertEqual(services.browse()["total"], 0)

    def test_relationship_correction_proposal_and_withdrawal_hide_previous_relation(self):
        replacement = self.propose(replaces_id=self.reference_link["id"])
        self.assertEqual(services.read(self.edition["id"])["relations"]["references"], [])
        self.approve(replacement)
        self.assertEqual(
            services.read(self.edition["id"])["relations"]["references"][0]["number"], 2
        )
        knowledge.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=replacement["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        self.assertEqual(services.read(self.edition["id"])["relations"]["references"], [])
        self.assertEqual(KnowledgeRevision.objects.count(), 3)
        self.assertEqual(KnowledgeAction.objects.count(), 4)

    def test_upstream_changed_sources_and_mid_read_policy_revocation_fail_closed(self):
        with patch.object(publication, "_citation_snapshot", return_value=[]):
            self.assertEqual(services.browse()["total"], 0)
        original = services._projection

        def revoke(*args):
            output = original(*args)
            revoked = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=None)
            revoked.enable()
            self.addCleanup(revoked.disable)
            return output

        with patch.object(services, "_projection", side_effect=revoke):
            with self.assertRaises(services.PreviewUnavailable):
                services.read(self.edition["id"])

    def test_owned_database_required_and_input_bounds(self):
        from apps.intake_workflow.guards import SyntheticWriteDenied

        with patch.object(
            services, "require_owned_database", side_effect=SyntheticWriteDenied("denied")
        ):
            with self.assertRaises(SyntheticWriteDenied):
                services.browse()
        for kwargs in (
            {"query": "x" * 81},
            {"query": "\x00"},
            {"page": 0},
            {"material": "transcript"},
            {"page": True},
        ):
            with self.assertRaises(services.InvalidFilter):
                services.browse(**kwargs)
        for position in (0, 13, True):
            with self.assertRaises(services.PreviewUnavailable):
                services.read_reference(self.edition["id"], position)

    def test_http_anonymous_navigation_headers_and_no_private_or_staff_routes(self):
        for url in ("/library-preview/", self.detail_url, self.source_url):
            page = self.client.get(
                url, {"q": "فرع", "category": "تصنيف تجريبي", "material": "reference", "page": 1}
            )
            self.assertEqual(page.status_code, 200, page.content)
            self.assertIn("no-store", page["Cache-Control"])
            self.assertIn("noindex", page["X-Robots-Tag"])
            self.assertEqual(page["Referrer-Policy"], "no-referrer")
            self.assertEqual(len(page.cookies), 0)
            for secret in (
                "PRIVATE",
                self.receipt["public_ref"],
                self.transcript_source_id,
                "casework/staff",
                "csrfmiddlewaretoken",
                self.transcript["link_id"],
            ):
                self.assertNotContains(page, secret)
        self.assertContains(self.client.get(self.source_url, {"q": "فرع"}), "q=%D9%81%D8%B1%D8%B9")
        self.assertEqual(self.client.get(self.detail_url + "transcript/").status_code, 404)
        self.assertEqual(self.client.get(self.detail_url + "references/2/").status_code, 404)
        self.assertEqual(self.client.head(self.detail_url).content, b"")

    def test_http_host_network_method_filter_and_authority_forgery_denied(self):
        for extra in (
            {"REMOTE_ADDR": "192.0.2.1"},
            {"HTTP_HOST": "attacker.test"},
            {"HTTP_X_FORWARDED_FOR": "127.0.0.1"},
            {"HTTP_FORWARDED": "host=127.0.0.1"},
        ):
            self.assertIn(self.client.get("/library-preview/", **extra).status_code, {400, 403})
        for method in ("post", "put", "delete", "patch"):
            self.assertEqual(getattr(self.client, method)(self.detail_url, {}).status_code, 405)
        for query in (
            "?q=a&q=b",
            "?next=https://attacker.test",
            "?subject_id=publisher",
            "?page=-1",
            "?material=transcript",
        ):
            self.assertEqual(self.client.get("/library-preview/" + query).status_code, 400)
        with override_settings(FATWA_LIBRARY_PREVIEW_ENABLED=False):
            self.assertEqual(self.client.get(self.detail_url).status_code, 404)
            self.assertEqual(self.client.get("/library-preview/preview.css").status_code, 404)

    def test_xss_query_is_escaped_and_previous_private_guards_preserved(self):
        response = self.client.get("/library-preview/", {"q": "<script>alert(1)</script>"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")
        self.assertEqual(self.client.get("/casework/staff/").status_code, 503)
        # Disabling the original casework web gate never enables a private route.
        with override_settings(FATWA_CASEWORK_WEB_ENABLED=True):
            self.assertEqual(
                self.client.get("/casework/staff/", REMOTE_ADDR="192.0.2.1").status_code, 403
            )

    def test_bounded_pagination_and_measured_read_cost(self):
        # One canonical fixture, actual SQL count/timing. No writes are performed.
        before = (
            PublicationEdition.objects.count(),
            KnowledgeRevision.objects.count(),
            KnowledgeAction.objects.count(),
        )
        with CaptureQueriesContext(connection) as queries:
            started = perf_counter()
            result = services.browse()
            elapsed = perf_counter() - started
        self.assertEqual(result["total"], 1)
        self.assertEqual(services.browse(page=2)["items"], [])
        self.assertEqual(
            before,
            (
                PublicationEdition.objects.count(),
                KnowledgeRevision.objects.count(),
                KnowledgeAction.objects.count(),
            ),
        )
        print(
            f"LIBRARY_PREVIEW_READ publications=1 relations=2 queries={len(queries)} seconds={elapsed:.4f}"
        )
        self.assertLess(len(queries), 100)
