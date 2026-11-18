"""Independent checks of 5aff9ba..5ec6373; no product repair or external data."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media import tests as media_fixtures
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.experimental_publication import services as publications
from apps.experimental_publication.tests import Authority, Directory
from apps.mufti_workspace import context
from apps.mufti_workspace import tests as workspace_fixtures
from apps.platform_recovery.integration import MaintenanceUnavailable
from apps.source_rights import registry
from apps.source_rights import services as rights
from apps.source_rights.tests import ENABLED, RightsFixture
from tests.casework import test_v11_answer_parts as native_parts
from tests.casework import test_v12_answer_edit as native_edit
from tests.casework.test_http import WEB_SETTINGS
from tests.v12_security_review import test_maintenance as maintenance_fixtures


@override_settings(**{**ENABLED, "FATWA_SOURCE_RIGHTS_ENFORCED": False})
class RightsDeltaTests(RightsFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.grant = rights.propose(
            **self.common,
            source_id=self.source["id"],
            expected_number=0,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="Synthetic independent V13 review",
            note="synthetic",
            ttl_minutes=1,
        )
        self.decision(self.grant)
        overlay = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.staff = {k: v for k, v in self.common.items() if k != "case_id"}

    def inspect(self, **changes):
        return registry.inspect_source(
            **{
                **self.common,
                "source_id": self.source["id"],
                **changes,
            }
        )

    def second_publication(self):
        receipt = cases.intake_case(
            original_question="Synthetic independent second question",
            source_event_id="v13-review-second",
            requester_id="v13-second",
            idempotency_key="v13-review-second",
            synthetic_fixtures_only=True,
        )
        common = dict(
            case_id=receipt["case_id"],
            subject_id="editor",
            provider=Directory([receipt["public_ref"]]),
            synthetic_fixtures_only=True,
        )
        draft = cases.save_answer(
            **common,
            expected_revision=1,
            expected_evidence_version=1,
            text="Synthetic separate answer",
        )
        cases.record_decision(
            **common,
            answer_id=draft["answers"][-1]["id"],
            expected_revision=2,
            expected_evidence_version=1,
            action="APPROVE",
            note="synthetic",
        )
        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(receipt["public_ref"])
        ):
            edition = publications.create_edition(
                **common,
                expected_revision=3,
                expected_evidence_version=1,
                title="Second synthetic publication",
                category="Only surviving category",
                body="Synthetic source-free editorial answer",
            )
            publications.act(**common, edition_id=edition["id"], action="REVIEW", reviewed=True)
            publications.act(
                **{**common, "subject_id": "publisher"}, edition_id=edition["id"], action="APPROVE"
            )
        self.staff["provider"] = Directory([self.receipt["public_ref"], receipt["public_ref"]])
        return receipt, edition

    def test_catalog_drops_early_expiry_before_metadata_search_facets_and_pages(self):
        _, second = self.second_publication()
        self.assertEqual(publications.library_catalog(**self.staff)["total"], 2)
        original = publications._projection
        for chosen in ({"page": 1}, {"page": 2}, {"query": self.heading.title_original}):
            clock = [timezone.now()]
            future = clock[0] + timedelta(minutes=2)
            projected = []

            def delayed(edition, **kwargs):
                result = original(edition, **kwargs)
                projected.append(str(edition.pk))
                if len(projected) == 2:
                    clock[0] = future
                return result

            with (
                self.subTest(chosen=chosen),
                patch.object(publications, "LIBRARY_PAGE_SIZE", 1),
                patch.object(rights.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(publications, "_projection", side_effect=delayed),
            ):
                result = publications.library_catalog(**self.staff, **chosen)
                self.assertEqual(set(projected), {self.edition["id"], second["id"]})
                self.assertEqual(result["total"], 0 if "query" in chosen else 1)
                self.assertEqual(result["categories"], [second["category"]])
                expected = [second["id"]] if chosen == {"page": 1} else []
                self.assertEqual([r["id"] for r in result["publications"]], expected)
                self.assertFalse(result["has_next"])
                self.assertNotIn(self.heading.title_original, str(result))

    def test_catalog_rechecks_scope_after_later_projection_before_returning_any_case(self):
        second_receipt, _ = self.second_publication()
        directory = self.staff["provider"]
        original = publications._projection
        calls = []

        def revoke(edition, **kwargs):
            result = original(edition, **kwargs)
            calls.append(edition.pk)
            if len(calls) == 2:
                directory.identities["editor"] = replace(
                    directory.identities["editor"],
                    case_keys=frozenset({second_receipt["public_ref"]}),
                )
            return result

        with patch.object(publications, "_projection", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                publications.library_catalog(**self.staff)
        self.assertEqual(len(calls), 2)

    def test_inspected_historic_grant_cannot_restore_current_publication_rights(self):
        self.assertEqual(publications.library_catalog(**self.staff)["total"], 1)
        self.proposal(number=1, uses=["READ"])
        before = (CaseEvent.objects.count(), rights.RightsAction.objects.count())
        result = self.inspect(revision_number=1)
        self.assertEqual(result["selected"].number, 1)
        self.assertEqual(result["current_number"], 2)
        self.assertEqual(result["current_state"], "PENDING")
        self.assertFalse(any(r["status"] == "ALLOWED" for r in result["usage_matrix"]))
        catalog = publications.library_catalog(**self.staff, query=self.heading.title_original)
        self.assertEqual(
            (catalog["publications"], catalog["categories"], catalog["total"]), ([], [], 0)
        )
        self.assertEqual(before, (CaseEvent.objects.count(), rights.RightsAction.objects.count()))

    def test_inspector_registration_boundary_survives_authority_allowing_both_cases(self):
        receipt, _ = self.second_publication()
        # Both identity and VIEW are deliberately allowed: registration must
        # independently prevent a guessed source UUID from crossing case scope.
        with patch.object(type(self.rights_authority), "permits", return_value=True):
            with self.assertRaisesMessage(cases.CaseConflict, "source_rights_target_unavailable"):
                self.inspect(case_id=receipt["case_id"], provider=self.staff["provider"])
        source = rights.register(
            **self.common, kind="PRIVATE_TRANSCRIPT", target_id=self.transcript["link_id"]
        )
        inspected = self.inspect(source_id=source["id"])
        self.assertTrue(inspected["material"]["has_recorded_text"])
        self.assertNotIn(self.transcript_text, str(inspected))
        self.assertFalse(any(r["status"] == "ALLOWED" for r in inspected["usage_matrix"]))


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    }
)
class NativeEvidenceDeltaTests(TransactionTestCase):
    setUp = media_fixtures.AnswerMediaTests.setUp
    save = media_fixtures.AnswerMediaTests.save
    approve = media_fixtures.AnswerMediaTests.approve
    release = media_fixtures.AnswerMediaTests.release
    open_editor = native_parts.NativePartRevisionTests.open_editor
    fields = native_edit.NativeAnswerEditTests.fields

    def test_empty_upload_cannot_reuse_old_evidence_or_keep_private_release(self):
        self.save()
        self.approve()
        self.release()
        package = media.staff_snapshot(**self.common)["latest_package"]
        page = self.open_editor()
        current = cases.read_case(**self.common)
        cases.add_followup(
            token=self.receipt["token"],
            text="Synthetic changed evidence",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        before = (
            Case.objects.get().revision,
            Case.objects.get().answers.count(),
            CaseEvent.objects.count(),
        )
        response = self.staff.post("/casework/staff/", self.fields(page))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            before,
            (
                Case.objects.get().revision,
                Case.objects.get().answers.count(),
                CaseEvent.objects.count(),
            ),
        )
        with self.assertRaises(cases.CaseConflict):
            media.requester_read(
                token=self.receipt["token"],
                part_id=package["parts"][1]["id"],
                synthetic_fixtures_only=True,
            )


@override_settings(FATWA_MUFTI_WORKSPACE_ENABLED=True, FATWA_CASEWORK_WEB_ENABLED=True)
class FrameDeltaTests(TransactionTestCase):
    setUp = workspace_fixtures.MuftiWorkspaceTests.setUp
    request = workspace_fixtures.MuftiWorkspaceTests.request

    def test_conflicting_server_frames_and_duplicate_browser_references_are_denied(self):
        other = workspace_fixtures.new_case("Synthetic secret other case")
        self.directory.grant(self.receipt["public_ref"], other["public_ref"])
        request = self.request(fields={"action": "knowledge_browse"})
        request.knowledge_authorized_case_ref = self.receipt["public_ref"]
        self.assertEqual(
            context.case_workspace(request)["mufti_workspace"]["case"]["case_id"],
            self.receipt["case_id"],
        )
        request.publication_authorized_case_ref = other["public_ref"]
        with self.assertRaises(cases.CaseConflict):
            context.case_workspace(request)
        del request.publication_authorized_case_ref
        request.POST = request.POST.copy()
        request.POST.setlist("case_ref", [self.receipt["public_ref"], other["public_ref"]])
        with self.assertRaises(cases.CaseConflict):
            context.case_workspace(request)


@override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=False)
class NewEntryMaintenanceTests(TransactionTestCase):
    setUp = maintenance_fixtures.MaintenanceP0Tests.setUp
    freeze = maintenance_fixtures.MaintenanceP0Tests.freeze

    def test_new_inspector_and_catalog_are_rejected_before_projection_while_frozen(self):
        self.freeze()
        for module, entry, extra in (
            (registry, registry.inspect_source, {"case_id": "unused", "source_id": "unused"}),
            (publications, publications.library_catalog, {}),
        ):
            with (
                self.subTest(entry=entry.__name__),
                patch.object(
                    module.services if module is registry else module,
                    "_enabled",
                    side_effect=AssertionError("projection reached without admission"),
                ),
            ):
                with self.assertRaises(MaintenanceUnavailable):
                    entry(
                        subject_id="synthetic", provider=None, synthetic_fixtures_only=True, **extra
                    )
