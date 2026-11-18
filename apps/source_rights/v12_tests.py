"""P1 inspection uses the existing case/source ledger and preserves P0 denials."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.reference.models import ReferenceHeading
from tests.casework.test_http import post

from . import registry, services
from .models import RightsAction, RightsRevision
from .tests import ENABLED, Authority, RightsFixture


@override_settings(**ENABLED)
class RegistryInspectionTests(RightsFixture, TransactionTestCase):
    def inspect(self, **kwargs):
        return registry.inspect_source(**{**self.common, "source_id": self.source["id"], **kwargs})

    def test_toc_identity_is_exact_and_cannot_imply_text_quote_or_publication(self):
        result = self.inspect()
        self.assertEqual(result["material"]["kind"], "TOC_METADATA")
        self.assertFalse(result["material"]["has_recorded_text"])
        self.assertEqual(result["source_sha256"], self.source["sha256"])
        identity = {row["label"]: row["value"] for row in result["material"]["identity"]}
        self.assertEqual(identity["مفتاح الطبعة"], self.heading.edition.edition_key)
        self.assertEqual(identity["بصمة ملف الاستيراد"], self.heading.edition.source_input_sha256)
        self.assertEqual(identity["الموضع في النسخة"], self.heading.source_row_id)
        self.assertEqual(result["current_state"], "UNKNOWN")
        self.assertEqual(result["comparison"], [])
        for row in result["usage_matrix"]:
            self.assertEqual(
                row["status"],
                "UNSUPPORTED"
                if row["code"] in {"FULL_TEXT", "QUOTE", "PUBLISH"}
                else "NOT_GRANTED",
            )
        self.allow()
        rows = {row["code"]: row for row in self.inspect()["usage_matrix"]}
        self.assertEqual(rows["CITE"]["status"], "ALLOWED")
        self.assertEqual(rows["PREVIEW_METADATA"]["status"], "ALLOWED")
        for usage in ("FULL_TEXT", "QUOTE", "PUBLISH"):
            self.assertFalse(self.permitted(usage))
            with self.assertRaises(cases.CaseConflict):
                self.proposal(uses=[usage], number=1)
            self.assertEqual(rows[usage]["status"], "UNSUPPORTED")

    def test_revision_comparison_preserves_predecessor_and_never_revives_old_grant(self):
        first = self.allow()
        second = self.proposal(uses=["READ"], number=1)
        for number in (0, 1, 2):
            result = self.inspect(revision_number=number)
            self.assertEqual(result["current_state"], "PENDING")
            self.assertTrue(all(r["status"] != "ALLOWED" for r in result["usage_matrix"]))
        result = self.inspect(revision_number=2)
        uses = next(row for row in result["comparison"] if row["field"] == "uses")
        self.assertEqual(set(uses["before"]), {"READ", "CITE", "RELATE", "PREVIEW_METADATA"})
        self.assertEqual(uses["after"], ["READ"])
        self.assertTrue(uses["changed"])
        self.assertEqual(result["previous_number"], 1)
        historic = self.inspect(revision_number=1)
        self.assertFalse(historic["selected_is_current"])
        self.assertEqual(historic["selected_actions"][0]["action"], "APPROVE")
        self.decision(second)
        self.assertEqual(self.inspect()["current_state"], "ALLOWED")
        self.assertFalse(self.permitted("CITE"))
        self.assertEqual(RightsRevision.objects.get(pk=first["id"]).number, 1)
        self.assertEqual(RightsRevision.objects.count(), 2)
        self.assertEqual(RightsAction.objects.count(), 2)

    def test_private_transcript_has_text_identity_but_never_exposes_text_or_public_uses(self):
        source = services.register(
            **self.common, kind="PRIVATE_TRANSCRIPT", target_id=self.transcript["link_id"]
        )
        proposal = self.proposal(source=source, uses=["READ", "RELATE"])
        self.decision(proposal)
        result = self.inspect(source_id=source["id"])
        self.assertTrue(result["material"]["has_recorded_text"])
        self.assertNotIn(self.transcript_text, str(result))
        rows = {row["code"]: row["status"] for row in result["usage_matrix"]}
        self.assertEqual(rows["READ"], "ALLOWED")
        self.assertEqual(rows["RELATE"], "ALLOWED")
        for use in ("CITE", "PREVIEW_METADATA", "QUOTE", "PUBLISH", "FULL_TEXT"):
            self.assertEqual(rows[use], "UNSUPPORTED")

    def test_wrong_source_case_revision_and_unregistered_source_are_rejected(self):
        other = cases.intake_case(
            original_question="Synthetic separate case",
            source_event_id="rights-inspection-other",
            requester_id="other",
            idempotency_key="rights-inspection-other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.inspect(case_id=other["case_id"], provider=Directory([other["public_ref"]]))
        # Same owned source catalog, but a different position registered only
        # for the other case must not become inspectable through a copied UUID.
        heading = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=3)
        with override_settings(FATWA_SOURCE_RIGHTS_AUTHORITY=Authority(other["public_ref"])):
            foreign = services.register(
                **{
                    **self.common,
                    "case_id": other["case_id"],
                    "provider": Directory([other["public_ref"]]),
                },
                kind="TOC_METADATA",
                target_id=heading.pk,
            )
        with self.assertRaisesMessage(cases.CaseConflict, "source_rights_target_unavailable"):
            self.inspect(source_id=foreign["id"])
        with self.assertRaises(cases.CaseConflict):
            self.inspect(provider=Directory([]))
        for number in (-1, 1, 65, True, "1"):
            with self.subTest(number=number), self.assertRaises(cases.CaseConflict):
                self.inspect(revision_number=number)
        with override_settings(FATWA_SOURCE_RIGHTS_AUTHORITY=None):
            with self.assertRaises(cases.CaseConflict):
                self.inspect()

    def test_revoked_expired_and_changed_sources_remain_inspectable_but_unavailable(self):
        first = services.propose(
            **self.common,
            source_id=self.source["id"],
            expected_number=0,
            uses=["READ", "CITE"],
            basis="Synthetic short grant",
            note="Synthetic",
            ttl_minutes=1,
        )
        self.decision(first)
        with patch.object(
            services.timezone, "now", return_value=timezone.now() + timedelta(minutes=2)
        ):
            result = self.inspect()
            self.assertEqual(result["current_state"], "EXPIRED")
            self.assertFalse(any(r["status"] == "ALLOWED" for r in result["usage_matrix"]))
        self.decision(first, "REVOKE")
        result = self.inspect()
        self.assertEqual(result["current_state"], "REVOKED")
        original = services._reference

        def changed(identity):
            snapshot, target = original(identity)
            return {**snapshot, "changed": True}, target

        with patch.object(services, "_reference", side_effect=changed):
            result = self.inspect()
            self.assertEqual(result["current_state"], "SOURCE_CHANGED")
            self.assertFalse(any(r["status"] == "ALLOWED" for r in result["usage_matrix"]))
        self.assertEqual(result["source_sha256"], self.source["sha256"])

    def test_review_controls_are_latest_only_and_match_explicit_authority(self):
        first = self.proposal()
        editor = services.desk(**self.common)["records"][0]["history"][0]
        self.assertEqual(editor["review_options"], [])
        reviewer = services.desk(**{**self.common, "subject_id": "publisher"})["records"][0]
        self.assertEqual(
            {o["value"] for o in reviewer["history"][0]["review_options"]},
            {"APPROVE", "REJECT", "REVOKE"},
        )
        self.decision(first)
        self.proposal(number=1, uses=["READ"])
        history = services.desk(**{**self.common, "subject_id": "publisher"})["records"][0][
            "history"
        ]
        self.assertTrue(history[0]["review_options"])
        self.assertEqual(history[1]["review_options"], [])
        self.assertFalse(history[1]["is_current"])

    def test_identity_revocation_during_projection_denies_the_inspector(self):
        original = services._current_source

        def revoke(*args):
            original(*args)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="revoked"
            )

        with patch.object(services, "_current_source", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.inspect()

    @override_settings(FATWA_CASEWORK_WEB_ENABLED=True)
    def test_http_native_inspection_retains_search_and_rejects_forgery(self):
        self.allow()
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        fields = dict(
            action="rights_inspect",
            case_ref=self.receipt["public_ref"],
            source_id=self.source["id"],
            revision_number="0",
            query="فرع",
            edition_id=str(self.catalog_id),
        )
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
            login = client.get("/casework/staff/login/")
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                login,
            )
            page = client.get("/casework/staff/")
            response = post(client, "/casework/staff/", fields, page)
            self.assertEqual(response.status_code, 200, response.content)
            for marker in (
                "rights-material-kind",
                "rights-usage-matrix",
                "rights-revision-comparison",
                "FULL_TEXT",
                "QUOTE",
                "PUBLISH",
                "العودة إلى نتائج المصادر نفسها",
            ):
                self.assertContains(response, marker)
            self.assertContains(response, 'name="query" value="فرع"')
            self.assertContains(response, f'name="edition_id" value="{self.catalog_id}"')
            self.assertIn("no-store", response["Cache-Control"])
            for extra in (
                {"subject_id": "publisher"},
                {"revision_number": ["0", "1"]},
                {"query": "a" * 101},
            ):
                self.assertEqual(
                    post(client, "/casework/staff/", {**fields, **extra}, response).status_code, 400
                )
            returned = post(
                client,
                "/casework/staff/",
                {
                    "action": "rights_desk",
                    "case_ref": self.receipt["public_ref"],
                    "query": fields["query"],
                    "edition_id": fields["edition_id"],
                },
                response,
            )
            self.assertEqual(returned.status_code, 200)
            self.assertContains(returned, 'id="rights-query" name="query" value="فرع"')
