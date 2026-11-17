"""Exact case/source rights supplement existing canonical and independent gates."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Directory
from apps.knowledge_links import services as knowledge
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.reference.models import ReferenceHeading
from apps.source_rights import services as rights
from apps.source_rights.tests import ENABLED, RightsFixture


@override_settings(**{**ENABLED, "FATWA_LIBRARY_PREVIEW_ENABLED": True})
class RightsBoundaryTests(RightsFixture, TransactionTestCase):
    def setUp(self):
        # Seed the accepted V10 historical state, then enable additive enforcement.
        super().setUp()
        overlay = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        overlay.enable()
        self.addCleanup(overlay.disable)
        edition = PublicationEdition.objects.get(pk=self.edition["id"])
        source = edition.citations[0]
        policy = PreviewPolicy(
            (PublicationGrant(str(edition.pk), edition.content_sha256),),
            (ReferenceGrant(self.catalog_id, 2, source["source_sha256"]),),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        overlay = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy)
        overlay.enable()
        self.addCleanup(overlay.disable)

    def grant(self, uses, *, number=0, source=None):
        revision = self.proposal(source=source, uses=uses, number=number)
        self.decision(revision)
        return revision

    def read(self, **common):
        return citations.read_source(
            **(common or self.common), edition_id=self.catalog_id, source_row_id=2
        )

    def test_unknown_search_denies_but_authorized_rights_review_can_bootstrap(self):
        self.assertEqual(citations.search_sources(**self.common)["editions"], [])
        with self.assertRaises(cases.CaseConflict):
            self.read()
        desk = rights.desk(
            **self.common, edition_id=self.catalog_id, query=self.heading.title_original
        )
        self.assertTrue(desk["search"]["results"])
        self.grant(["READ"])
        result = citations.search_sources(**self.common, edition_id=self.catalog_id)
        self.assertEqual([row["source"]["source_row_id"] for row in result["results"]], [2])
        located = citations.search_sources(
            **self.common, edition_id=self.catalog_id, printed_page=2
        )
        self.assertEqual(len(located["results"]), 1)
        self.assertEqual(self.read()["source"]["source_row_id"], 2)
        with self.assertRaises(cases.CaseConflict):
            citations.read_citations(**self.common)
        with self.assertRaises(cases.CaseConflict):
            citations._search_sources_for_rights_review(
                **{**self.common, "provider": Directory([])}, edition_id=self.catalog_id
            )

    def test_cite_revocation_blocks_save_current_publication_and_preserves_history(self):
        grant = self.allow()
        source = self.read()
        before = Case.objects.get(pk=self.receipt["case_id"]).revision
        self.decision(grant, "REVOKE")
        with self.assertRaises(cases.CaseConflict):
            citations.save_cited_answer(
                **self.common,
                text="Unchanged human answer",
                selections=[
                    dict(
                        edition_id=self.catalog_id,
                        source_row_id=2,
                        source_sha256=source["source_sha256"],
                        editorial_note="",
                    )
                ],
                expected_revision=before,
                expected_evidence_version=2,
            )
        with self.assertRaises(cases.CaseConflict):
            citations.read_citations(**self.common)
        self.assertEqual(
            publications.library(**{k: v for k, v in self.common.items() if k != "case_id"}), []
        )
        self.assertEqual(preview.browse()["total"], 0)
        with self.assertRaises(preview.PreviewUnavailable):
            preview.read(self.edition["id"])
        history = citations.read_citation_history(**self.common)["revisions"][0]["citations"][0]
        self.assertTrue(history["rights_restricted"])
        self.assertIsNone(history["source"])
        self.assertFalse(history["current_source_available"])
        self.assertEqual(Case.objects.get(pk=self.receipt["case_id"]).revision, before)
        # Authorized rights inspection remains usable to repair revoked citations.
        self.assertTrue(rights.desk(**self.common)["records"])

    def test_missing_configuration_expiry_and_other_case_never_inherit_grant(self):
        self.allow()
        self.assertTrue(self.read())
        for values in (
            {"FATWA_SOURCE_RIGHTS_ENABLED": False},
            {"FATWA_SOURCE_RIGHTS_AUTHORITY": None},
        ):
            with self.subTest(values=values), override_settings(**values):
                with self.assertRaises(cases.CaseConflict):
                    self.read()
                with self.assertRaises(cases.CaseConflict):
                    citations.read_citations(**self.common)
        installed = citations.django_apps.is_installed
        with patch.object(
            citations.django_apps,
            "is_installed",
            side_effect=lambda name: False if name == "apps.source_rights" else installed(name),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.read()
        with patch.object(rights.timezone, "now", return_value=timezone.now() + timedelta(hours=2)):
            with self.assertRaises(cases.CaseConflict):
                self.read()
        other = cases.intake_case(
            original_question="Other synthetic question",
            source_event_id="rights-other",
            requester_id="rights-other",
            idempotency_key="rights-other",
            synthetic_fixtures_only=True,
        )
        common = {
            **self.common,
            "case_id": other["case_id"],
            "provider": Directory([other["public_ref"]]),
        }
        with self.assertRaises(cases.CaseConflict):
            self.read(**common)
        self.assertEqual(citations.search_sources(**common)["editions"], [])
        # No source exists in this answer: unrelated rights configuration does not lock it.
        plain = cases.save_answer(
            **common, text="Human text only", expected_revision=1, expected_evidence_version=1
        )
        with override_settings(FATWA_SOURCE_RIGHTS_AUTHORITY=None):
            self.assertEqual(
                citations.read_citations(**common, answer_id=plain["answers"][-1]["id"]), []
            )

    def test_preview_metadata_is_independent_and_filtered_before_search_counts(self):
        self.grant(["READ", "CITE", "RELATE"])
        book = self.read()["source"]["work_title"]
        self.assertEqual(preview.browse()["total"], 1)
        self.assertEqual(preview.read(self.edition["id"])["references"], [])
        self.assertEqual(preview.browse(query=book)["total"], 0)
        self.assertEqual(preview.browse(material="reference")["total"], 0)
        with self.assertRaises(preview.PreviewUnavailable):
            preview.read_reference(self.edition["id"], 1)
        self.grant(["READ", "CITE", "RELATE", "PREVIEW_METADATA"], number=1)
        self.assertEqual(preview.browse(query=book)["total"], 1)
        self.assertEqual(len(preview.read(self.edition["id"])["references"]), 1)
        self.assertEqual(
            preview.read_reference(self.edition["id"], 1)["source"]["work_title"], book
        )

    def test_relationship_read_and_relate_are_independent_and_current(self):
        self.grant(["READ", "CITE"])
        with self.assertRaises(cases.CaseConflict):
            self.propose()
        self.grant(["READ", "CITE", "RELATE"], number=1)
        link = self.propose()
        self.approve(link)
        self.assertEqual(len(knowledge.browse(**self.access)["links"]), 1)
        self.grant(["CITE", "RELATE"], number=2)
        self.assertEqual(knowledge.browse(**self.access)["links"], [])
        with self.assertRaises(cases.CaseConflict):
            knowledge.open_material(**self.access, revision_id=link["id"])
        self.grant(["READ", "CITE"], number=3)
        self.assertEqual(knowledge.browse(**self.access)["links"], [])
        with self.assertRaises(cases.CaseConflict):
            knowledge.open_material(**self.access, revision_id=link["id"])

    def test_private_transcript_requires_read_relate_and_original_open_authority(self):
        self.allow()
        source = rights.register(
            **self.common, kind="PRIVATE_TRANSCRIPT", target_id=self.transcript["link_id"]
        )
        self.grant(["RELATE"], source=source)
        link = self.propose("TRANSCRIPT")
        self.approve(link)
        with self.assertRaises(cases.CaseConflict):
            knowledge.open_material(**self.access, revision_id=link["id"])
        self.grant(["READ", "RELATE"], source=source, number=1)
        opened = knowledge.open_material(**self.access, revision_id=link["id"])
        self.assertEqual(opened["material"]["text"], self.transcript_text)
        self.authority.allow_open = False
        with self.assertRaises(cases.CaseConflict):
            knowledge.open_material(**self.access, revision_id=link["id"])
        self.assertFalse(preview.read(self.edition["id"])["relations"]["private_related"])

    def test_rights_correction_can_replace_revoked_source_without_reusing_its_grant(self):
        first = self.allow()
        before = citations.read_citations(**self.common)[0]
        replacement = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=3)
        self.allow(replacement)
        self.decision(first, "REVOKE")
        result = rights.correct_citation(
            **self.common,
            citation_id=before["id"],
            target_id=replacement.pk,
            note="Human exact-source correction",
            expected_revision=4,
            expected_evidence_version=2,
        )
        self.assertEqual(result["status"], "UNDER_REVIEW")
        self.assertIsNone(result["approved_answer_id"])
        self.assertEqual(citations.read_citations(**self.common)[0]["source"]["source_row_id"], 3)

    def test_direct_services_require_maintenance_admission_before_database_work(self):
        from apps.platform_recovery.integration import MaintenanceUnavailable

        with override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True, FATWA_RECOVERY_MAINTENANCE_ROOT=None
        ):
            for call in (
                lambda: citations.search_sources(**self.common),
                lambda: knowledge.browse(**self.access),
                lambda: publications.library(
                    **{k: v for k, v in self.common.items() if k != "case_id"}
                ),
                lambda: preview.browse(),
                lambda: rights.desk(**self.common),
            ):
                with self.subTest(call=call), self.assertRaises(MaintenanceUnavailable):
                    call()
