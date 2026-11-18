"""P0: real canonical consumers cannot bypass current exact source rights."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_citations import services as citations
from apps.case_citations.models import AnswerCitation
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.knowledge_links import services as knowledge
from apps.knowledge_links.models import KnowledgeRevision
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from apps.research_workspace import services as research
from apps.research_workspace.tests import SyntheticRights
from tests.reference.test_catalog import fixture

from . import services
from .tests import ENABLED, RightsFixture

USES = ["READ", "CITE", "RELATE", "PREVIEW_METADATA"]


@override_settings(
    **ENABLED,
    FATWA_LIBRARY_PREVIEW_ENABLED=True,
    FATWA_RESEARCH_WORKSPACE_ENABLED=True,
    ROOT_URLCONF="config.campaign_urls",
)
class StrictConsumerTests(RightsFixture, TransactionTestCase):
    def setUp(self):
        # Import historical approved synthetic records, then require the ledger.
        # No approval or registration is inferred from this migration fixture.
        historical = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=False)
        historical.enable()
        self.addCleanup(historical.disable)
        super().setUp()
        self.link = self.propose()
        self.approve(self.link)
        self.number = 0
        self.granted = self.grant()
        edition = PublicationEdition.objects.get(pk=self.edition["id"])
        self.item = edition.citations[0]
        self.resource = research._source_resource(self.item["source"], self.item["source_sha256"])
        self.preview_policy = PreviewPolicy(
            (PublicationGrant(str(edition.pk), edition.content_sha256),),
            (ReferenceGrant(self.catalog_id, 2, self.item["source_sha256"]),),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        self.legacy = SyntheticRights(self.receipt["public_ref"])
        settings = override_settings(
            FATWA_SOURCE_RIGHTS_ENFORCED=True,
            FATWA_LIBRARY_PREVIEW_POLICY=self.preview_policy,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.legacy,
        )
        settings.enable()
        self.addCleanup(settings.disable)

    def grant(self, uses=None):
        row = services.propose(
            **self.common,
            source_id=self.source["id"],
            expected_number=self.number,
            uses=USES if uses is None else uses,
            basis="Explicit synthetic rights basis",
            note="Reviewed synthetic source",
            ttl_minutes=1,
        )
        self.number += 1
        self.decision(row)
        return row

    def library(self):
        return publications.library(**{k: v for k, v in self.common.items() if k != "case_id"})

    def hidden(self):
        self.assertEqual(self.library(), [])
        self.assertEqual(preview.browse()["total"], 0)
        for read in (
            lambda: preview.read(self.edition["id"]),
            lambda: preview.read_reference(self.edition["id"], 1),
        ):
            with self.assertRaises(preview.PreviewUnavailable):
                read()
        self.assertIsNone(publications.desk(**self.common)["visible_edition"])

    def unchanged(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        self.assertEqual(case.source.original_question, "PRIVATE QUESTION requester@example.test")
        self.assertEqual(AnswerRevision.objects.get().text, "PRIVATE ANSWER")
        self.assertEqual(AnswerCitation.objects.count(), 1)
        self.assertIsNotNone(case.approved_answer_id)

    def test_legacy_workspace_policy_cannot_expose_unregistered_reference_or_transcript(self):
        found = research.search(
            **self.common, kind="REFERENCE", edition_id=self.catalog_id, query="فرع"
        )
        self.assertEqual([r["source"]["source_row_id"] for r in found["results"]], [2])
        other = citations._source(self.catalog_id, 3)
        resource = research._source_resource(other["source"], other["source_sha256"])
        with self.assertRaises(cases.CaseConflict):
            research.open_resource(**self.common, resource=resource)
        self.assertEqual(research.search(**self.common, kind="TRANSCRIPT")["results"], [])
        with transaction.atomic():
            case = Case.objects.select_for_update().get(pk=self.receipt["case_id"])
            found = citations._search_sources_for_locked_case(
                case, edition_id=self.catalog_id, query="فرع"
            )
        self.assertEqual([r["source"]["source_row_id"] for r in found["results"]], [2])
        self.assertTrue(self.legacy.calls)

    def test_independent_read_cite_preview_loss_disables_current_publication(self):
        self.assertEqual(len(self.library()), 1)
        self.assertEqual(preview.browse()["total"], 1)
        for usage in ("READ", "CITE", "PREVIEW_METADATA"):
            with self.subTest(usage=usage):
                self.grant([u for u in USES if u != usage])
                self.hidden()
                if usage in {"READ", "CITE"}:
                    with self.assertRaises(cases.CaseConflict):
                        citations.read_citations(**self.common)
                if usage == "READ":
                    with self.assertRaises(cases.CaseConflict):
                        research.open_resource(**self.common, resource=self.resource)
                    history = citations.read_citation_history(**self.common)
                    self.assertIsNone(history["revisions"][0]["citations"][0]["source"])
                    self.assertNotIn("PRIVATE NOTE", str(history))
                self.unchanged()
                self.grant()
                self.assertEqual(preview.browse()["total"], 1)

    def test_relate_loss_hides_approved_relation_without_erasing_publication_or_history(self):
        self.assertEqual(len(knowledge.browse(**self.access)["links"]), 1)
        self.grant([u for u in USES if u != "RELATE"])
        self.assertEqual(knowledge.browse(**self.access)["links"], [])
        with self.assertRaises(cases.CaseConflict):
            knowledge.open_material(**self.access, revision_id=self.link["id"])
        self.assertEqual(len(self.library()), 1)
        self.assertEqual(preview.read(self.edition["id"])["relations"]["references"], [])
        self.assertEqual(KnowledgeRevision.objects.count(), 1)
        self.unchanged()

    def test_expiry_blocks_read_cite_relate_and_preview_with_valid_actor_and_preview_policy(self):
        future = timezone.now() + timedelta(minutes=2)
        with patch.object(services.timezone, "now", return_value=future):
            for usage in USES:
                self.assertFalse(self.permitted(usage))
            with self.assertRaises(cases.CaseConflict):
                citations.read_source(**self.common, edition_id=self.catalog_id, source_row_id=2)
            with self.assertRaises(cases.CaseConflict):
                research.open_resource(**self.common, resource=self.resource)
            with self.assertRaises(cases.CaseConflict):
                citations.save_cited_answer(
                    **self.common,
                    text="Must not overwrite",
                    expected_revision=4,
                    expected_evidence_version=2,
                    selections=[
                        dict(
                            edition_id=self.catalog_id,
                            source_row_id=2,
                            source_sha256=self.item["source_sha256"],
                            editorial_note="",
                        )
                    ],
                )
            with self.assertRaises(cases.CaseConflict):
                knowledge.open_material(**self.access, revision_id=self.link["id"])
            self.hidden()
            history = knowledge.history(**self.access)["history"][0]
            self.assertIsNone(history["snapshot"])
            self.assertEqual(history["reason"], "")
        self.unchanged()

    def test_revocation_allows_explicit_withdrawal_and_does_not_resurrect_older_publication(self):
        second = self.new_publication()
        self.decision(self.granted, "REVOKE")
        self.hidden()
        knowledge.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=self.link["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        publications.act(
            **{**self.common, "subject_id": "publisher"}, edition_id=second["id"], action="WITHDRAW"
        )
        self.grant()
        self.assertEqual(self.library(), [])
        self.assertEqual(knowledge.history(**self.access)["history"][0]["state"], "WITHDRAWN")
        self.assertEqual(PublicationEdition.objects.count(), 2)
        self.unchanged()

    def test_rights_loss_blocks_review_and_independent_approval_of_existing_candidate(self):
        candidate = publications.create_edition(
            **self.common,
            expected_revision=4,
            expected_evidence_version=2,
            title="Synthetic candidate",
            category="Synthetic",
            body="Synthetic edited answer",
        )
        publications.act(**self.common, edition_id=candidate["id"], action="REVIEW", reviewed=True)
        self.grant(["CITE", "RELATE", "PREVIEW_METADATA"])
        with self.assertRaises(cases.CaseConflict):
            publications.act(
                **{**self.common, "subject_id": "publisher"},
                edition_id=candidate["id"],
                action="APPROVE",
            )
        self.assertFalse(
            PublicationEdition.objects.get(pk=candidate["id"])
            .actions.filter(action="APPROVE")
            .exists()
        )
        self.unchanged()

    def test_missing_app_authority_disabled_ledger_and_malformed_flags_never_fall_back(self):
        for config in (
            {"FATWA_SOURCE_RIGHTS_AUTHORITY": None},
            {"FATWA_SOURCE_RIGHTS_ENABLED": False},
            {"FATWA_SOURCE_RIGHTS_ENFORCED": "false"},
            {"FATWA_SOURCE_RIGHTS_ENFORCED": None},
            {"FATWA_SOURCE_RIGHTS_ENFORCED": 0},
        ):
            with self.subTest(config=config), override_settings(**config):
                with self.assertRaises(cases.CaseConflict):
                    research.open_resource(**self.common, resource=self.resource)
                self.hidden()
        installed = citations.django_apps.is_installed
        with patch.object(
            citations.django_apps,
            "is_installed",
            side_effect=lambda app: app != "apps.source_rights" and installed(app),
        ):
            self.hidden()
            with self.assertRaises(cases.CaseConflict):
                research.open_resource(**self.common, resource=self.resource)
        with patch.object(
            citations.django_apps,
            "is_installed",
            side_effect=lambda app: app != "apps.case_citations" and installed(app),
        ):
            self.hidden()
        self.unchanged()

    def test_exact_edition_and_source_version_pins_cannot_inherit_rights(self):
        spec, rows = fixture()
        spec = replace(
            spec,
            source_book_id="622",
            edition_key="another-synthetic-edition",
            source_archive_sha256="c" * 64,
            source_input_sha256="d" * 64,
        )
        dry = ingest_catalog(spec, rows)
        second = ingest_catalog(spec, rows, dry_run=False, expected_checksum=dry.checksum)
        heading = ReferenceHeading.objects.get(edition_id=second.edition_id, source_row_id=2)
        self.register_heading(heading)
        with self.assertRaises(cases.CaseConflict):
            citations.read_source(**self.common, edition_id=second.edition_id, source_row_id=2)
        with self.assertRaises(cases.CaseConflict):
            research.open_resource(**self.common, resource=replace(self.resource, sha256="0" * 64))
        original = citations._source

        def changed(edition, row):
            result = original(edition, row)
            if edition == self.catalog_id and row == 2:
                result["source"] = {**result["source"], "printed_page": 999}
                result["source_sha256"] = citations._digest(result["source"])
            return result

        with patch.object(citations, "_source", side_effect=changed):
            self.hidden()
            with self.assertRaises(cases.CaseConflict):
                research.open_resource(**self.common, resource=self.resource)
        self.unchanged()

    def test_correction_rebinds_current_answer_and_redacts_revoked_previous_source_notes(self):
        before = citations.read_citations(**self.common)[0]
        replacement = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=3)
        self.allow(replacement)
        self.decision(self.granted, "REVOKE")
        result = services.correct_citation(
            **self.common,
            citation_id=before["id"],
            target_id=replacement.pk,
            note="PRIVATE previous source quotation in correction note",
            expected_revision=4,
            expected_evidence_version=2,
        )
        self.assertIsNone(result["approved_answer_id"])
        self.assertEqual(result["status"], "UNDER_REVIEW")
        self.assertEqual(citations.read_citations(**self.common)[0]["source"]["source_row_id"], 3)
        history = citations.read_citation_history(**self.common)
        self.assertEqual(history["revisions"][0]["citations"][0]["correction"]["reason"], "")
        self.assertIsNone(history["revisions"][0]["citations"][0]["correction"]["previous_source"])
        self.assertIsNone(history["revisions"][1]["citations"][0]["source"])
        self.assertNotIn("PRIVATE previous source quotation", str(history))
        self.assertEqual(
            list(AnswerRevision.objects.values_list("text", flat=True)),
            ["PRIVATE ANSWER", "PRIVATE ANSWER"],
        )
        self.assertEqual(self.library(), [])
        knowledge.act(
            **{**self.access, "subject_id": "publisher"},
            revision_id=self.link["id"],
            action="WITHDRAW",
            confirmed=True,
        )
        self.assertEqual(knowledge.history(**self.access)["history"][0]["state"], "WITHDRAWN")

    def test_anonymous_http_returns_uniform_denial_after_source_revocation(self):
        client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        url = f"/library-preview/editions/{self.edition['id']}/"
        self.assertEqual(client.get(url).status_code, 200)
        self.decision(self.granted, "REVOKE")
        for target in (url, url + "references/1/"):
            response = client.get(target)
            self.assertEqual(response.status_code, 404)
            self.assertIn("no-store", response["Cache-Control"])
            for private in (
                self.item["source"]["heading_title"],
                self.receipt["public_ref"],
                "PRIVATE ANSWER",
                self.edition["title"],
            ):
                self.assertNotContains(response, private, status_code=404)
        self.unchanged()
