"""Multi-result regression from the independent BLOCKED review of 37c58a4.

A source grant expires while a second independently approved publication is
projected. The first result and all derived metadata must disappear together.
"""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority, Directory
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.source_rights import services as rights
from apps.source_rights.tests import ENABLED, RightsFixture
from tests.casework.test_http import WEB_SETTINGS


@override_settings(
    **{**ENABLED, "FATWA_LIBRARY_PREVIEW_ENABLED": True, "FATWA_SOURCE_RIGHTS_ENFORCED": False}
)
class CatalogExpiryTests(RightsFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.first = PublicationEdition.objects.get(pk=self.edition["id"])
        overlay = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        overlay.enable()
        self.addCleanup(overlay.disable)
        grant = rights.propose(
            **self.common,
            source_id=self.source["id"],
            expected_number=0,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="Synthetic independent review",
            note="Synthetic",
            ttl_minutes=1,
        )
        self.decision(grant)
        receipt = cases.intake_case(
            original_question="Synthetic second question",
            source_event_id="batch-expiry-2",
            requester_id="synthetic-second",
            idempotency_key="batch-expiry-2",
            synthetic_fixtures_only=True,
        )
        common = dict(
            case_id=receipt["case_id"],
            subject_id="editor",
            provider=Directory([receipt["public_ref"]]),
            synthetic_fixtures_only=True,
        )
        answer = cases.save_answer(
            **common,
            expected_revision=1,
            expected_evidence_version=1,
            text="Synthetic second answer",
        )
        cases.record_decision(
            **common,
            answer_id=answer["answers"][-1]["id"],
            expected_revision=2,
            expected_evidence_version=1,
            action="APPROVE",
            note="synthetic",
        )
        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(receipt["public_ref"])
        ):
            second = publications.create_edition(
                **common,
                expected_revision=3,
                expected_evidence_version=1,
                title="Synthetic second publication",
                category="Second synthetic category",
                body="Synthetic second editorial body",
            )
            publications.act(**common, edition_id=second["id"], action="REVIEW", reviewed=True)
            publications.act(
                **{**common, "subject_id": "publisher"}, edition_id=second["id"], action="APPROVE"
            )
        self.second = PublicationEdition.objects.get(pk=second["id"])
        self.staff = dict(
            subject_id="editor",
            synthetic_fixtures_only=True,
            provider=Directory([self.receipt["public_ref"], receipt["public_ref"]]),
        )
        self.policy = PreviewPolicy(
            tuple(
                PublicationGrant(str(row.pk), row.content_sha256)
                for row in (self.first, self.second)
            ),
            (ReferenceGrant(self.catalog_id, 2, self.first.citations[0]["source_sha256"]),),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        overlay = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.policy)
        overlay.enable()
        self.addCleanup(overlay.disable)

    @contextmanager
    def expire_during_second(self, module=preview):
        clock = [timezone.now()]
        future = clock[0] + timedelta(minutes=2)
        original = module._projection

        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            edition = args[1] if module is preview else args[0]
            if edition.pk == self.second.pk:
                clock[0] = future
            return result

        with (
            patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
            patch.object(module, "_projection", side_effect=delayed),
        ):
            yield

    def test_prior_item_expiry_during_later_projection(self):
        self.assertEqual(preview.browse()["total"], 2)
        with self.expire_during_second():
            result = preview.browse()
            with self.assertRaises(preview.PreviewUnavailable):
                preview.read(self.edition["id"])
            self.assertEqual(preview.read(str(self.second.pk))["id"], str(self.second.pk))
            self.assertEqual(result["total"], 1, result)
            self.assertEqual([item["id"] for item in result["items"]], [str(self.second.pk)])
            self.assertEqual(result["categories"], [self.second.category])

    def test_search_and_filters_do_not_retain_expired_source_metadata(self):
        source = self.first.citations[0]["source"]
        filters = [
            dict(query=self.first.title),
            dict(category=self.first.category),
            dict(material="reference"),
        ]
        filters.extend(
            dict(query=str(source[key]))
            for key in ("work_title", "edition_title", "heading_title", "printed_page")
            if source[key]
        )
        for chosen in filters:
            with self.subTest(filters=chosen):
                self.assertEqual(preview.browse(**chosen)["total"], 1)
                with self.expire_during_second():
                    result = preview.browse(**chosen)
                self.assertEqual(result["items"], [])
                self.assertEqual(result["total"], 0)
                self.assertEqual(result["categories"], [self.second.category])
                self.assertFalse(result["has_next"])

    def test_pagination_uses_only_the_final_eligible_collection(self):
        with patch.object(preview, "PAGE_SIZE", 1):
            self.assertTrue(preview.browse()["has_next"])
            for page in (1, 2):
                with self.subTest(page=page), self.expire_during_second():
                    result = preview.browse(page=page)
                self.assertEqual(result["total"], 1)
                self.assertEqual(
                    [item["id"] for item in result["items"]],
                    [str(self.second.pk)] if page == 1 else [],
                )
                self.assertEqual(result["categories"], [self.second.category])
                self.assertFalse(result["has_next"])

    def test_staff_library_rechecks_prior_result_after_later_projection(self):
        self.assertEqual(len(publications.library(**self.staff)), 2)
        for chosen in ({}, dict(query=self.first.title), dict(category=self.first.category)):
            with self.subTest(filters=chosen), self.expire_during_second(publications):
                result = publications.library(**self.staff, **chosen)
            self.assertEqual(
                [item["id"] for item in result], [] if chosen else [str(self.second.pk)]
            )

    def test_http_get_and_head_do_not_disclose_expired_row_or_category(self):
        options = {
            **WEB_SETTINGS,
            "ROOT_URLCONF": "config.campaign_urls",
            "MIDDLEWARE": [
                "apps.platform_recovery.middleware.MaintenanceGuard",
                "apps.library_preview.guard.PreviewCompositionGuard",
                "django.middleware.csrf.CsrfViewMiddleware",
            ],
        }
        with override_settings(**options):
            client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
            for method in (client.get, client.head):
                with self.subTest(method=method), self.expire_during_second():
                    response = method("/library-preview/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                for forbidden in (
                    self.first.title,
                    self.first.category,
                    self.heading.title_original,
                    self.receipt["public_ref"],
                ):
                    self.assertNotIn(forbidden, response.content.decode())
                self.assertEqual(response.context["total"], 1)
                self.assertEqual(response.context["categories"], [self.second.category])

    def test_expiry_during_final_batch_validation_uses_one_final_clock(self):
        for module, read, trigger in (
            (preview, preview.browse, 3),
            (publications, lambda: publications.library(**self.staff), 2),
        ):
            clock = [timezone.now()]
            future = clock[0] + timedelta(minutes=2)
            original = publications._require_publication_sources
            calls = []

            def delayed(case, sources):
                result = original(case, sources)
                if case.pk == self.second.case_id:
                    calls.append(case.pk)
                    if len(calls) == trigger:
                        clock[0] = future
                return result

            with (
                self.subTest(surface=module.__name__),
                patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(publications, "_require_publication_sources", side_effect=delayed),
            ):
                result = read()
                self.assertEqual(len(calls), trigger)
                items = result["items"] if module is preview else result
                self.assertEqual([item["id"] for item in items], [str(self.second.pk)])
                if module is preview:
                    self.assertEqual(result["categories"], [self.second.category])
                    self.assertEqual(result["total"], 1)

    def test_expiry_during_filtering_fails_entire_response_closed(self):
        prefix = self.first.title + " " + self.first.category + " "
        for module, read, error in (
            (preview, preview.browse, preview.PreviewUnavailable),
            (publications, lambda: publications.library(**self.staff), cases.CaseConflict),
        ):
            clock = [timezone.now()]
            future = clock[0] + timedelta(minutes=2)
            original = module.normalize_editorial_search

            def delayed(value):
                result = original(value)
                if value.startswith(prefix):
                    clock[0] = future
                return result

            with (
                self.subTest(surface=module.__name__),
                patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(module, "normalize_editorial_search", side_effect=delayed),
            ):
                with self.assertRaises(error):
                    read()

    def grant_transcript(self):
        source = rights.register(
            **self.common, kind="PRIVATE_TRANSCRIPT", target_id=self.transcript["link_id"]
        )
        grant = rights.propose(
            **self.common,
            source_id=source["id"],
            expected_number=0,
            uses=["READ", "RELATE"],
            basis="Synthetic transcript rights",
            note="Synthetic",
            ttl_minutes=30,
        )
        self.decision(grant)

    def test_related_material_collection_rejects_expiry_during_later_projection(self):
        from apps.knowledge_links import services as knowledge

        self.grant_transcript()
        for kind in ("REFERENCE", "TRANSCRIPT"):
            self.approve(self.propose(kind))
        self.assertEqual(len(knowledge.browse(**self.access)["links"]), 2)
        clock = [timezone.now()]
        future = clock[0] + timedelta(minutes=2)
        original = knowledge._public
        projected = []

        def delayed(row):
            result = original(row)
            projected.append(row.pk)
            if len(projected) == 2:
                clock[0] = future
            return result

        with (
            patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
            patch.object(knowledge, "_public", side_effect=delayed),
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "current_source_rights_required"):
                knowledge.browse(**self.access)
        self.assertEqual(len(projected), 2)
        # The guard's execution-local state cannot contaminate a later read.
        self.assertEqual(len(knowledge.browse(**self.access)["links"]), 2)

    def test_research_collection_rejects_expiry_after_final_item_checks(self):
        from apps.research_workspace import services as research
        from apps.research_workspace.source_rights_adapter import SourceRightsAdapter

        self.grant_transcript()
        clock = [timezone.now()]
        future = clock[0] + timedelta(minutes=2)
        original = research._recheck

        def delayed(*args):
            original(*args)
            clock[0] = future

        with override_settings(
            FATWA_RESEARCH_WORKSPACE_ENABLED=True,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
        ):
            baseline = research.search(**self.common, edition_id=self.catalog_id)
            self.assertEqual({r["kind"] for r in baseline["results"]}, {"REFERENCE", "TRANSCRIPT"})
            with (
                patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(research, "_recheck", side_effect=delayed),
            ):
                with self.assertRaisesMessage(cases.CaseConflict, "current_source_rights_required"):
                    research.search(**self.common, edition_id=self.catalog_id)

    def test_direct_citation_search_and_suggestions_recheck_after_collection(self):
        from apps.case_citations import services as citations

        for read in (citations.search_sources, citations.suggest_sources):
            clock = [timezone.now()]
            future = clock[0] + timedelta(minutes=2)
            original = citations._search_sources_for_locked_case

            def delayed(*args, **kwargs):
                result = original(*args, **kwargs)
                self.assertTrue(result["results"])
                clock[0] = future
                return result

            with (
                self.subTest(surface=read.__name__),
                patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(citations, "_search_sources_for_locked_case", side_effect=delayed),
            ):
                with self.assertRaisesMessage(cases.CaseConflict, "current_source_rights_required"):
                    read(**self.common, edition_id=self.catalog_id)
