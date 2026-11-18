"""Only synthetic identities/decisions; these tests are NOT human gold review."""

import copy
import json

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_workspace.tests import SETTINGS, ResearchFixture
from tests.casework.test_http import post

from . import review
from .models import EvaluationDecision, EvaluationRevision
from .views import proposed_bundle


class Authority(review.EvaluationAuthority):
    def __init__(self, ref):
        self.ref, self.denied = ref, set()

    def permits(self, **kw):
        return (
            kw["case_ref"] == self.ref
            and kw["provider_id"] == "synthetic-publication-directory"
            and kw["auth_epoch"] == "epoch-1"
            and kw["action"] not in self.denied
            and (
                kw["action"] == "VIEW"
                or (kw["action"] == "PROPOSE" and kw["subject_id"] == "editor")
                or (kw["action"] in {"APPROVE", "REJECT"} and kw["subject_id"] == "publisher")
            )
        )


class ReviewDirectory(Directory):
    def authenticate(self, credential):
        if credential == "synthetic-publisher-credential-32-characters":
            return self.resolve("publisher")
        return super().authenticate(credential)


class ReviewFixture(ResearchFixture):
    def setUp(self):
        super().setUp()
        self.directory = ReviewDirectory([self.receipt["public_ref"]])
        self.common["provider"] = self.directory
        self.review_authority = Authority(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_ARABIC_SEARCH_REVIEW_ENABLED=True,
            FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY=self.review_authority,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.bundle = proposed_bundle()
        self.bundle["queries"] = self.bundle["queries"][:2]

    def propose(self, number=0, bundle=None):
        return review.propose(
            **self.common,
            expected_number=number,
            bundle=bundle or self.bundle,
            note="Synthetic authored judgement revision",
        )

    def decision(self, row, **kwargs):
        args = dict(
            revision_id=row["id"],
            corpus_sha256=row["corpus_sha256"],
            judgements_sha256=row["judgements_sha256"],
            action="APPROVE",
            confirmed=True,
            reviews=[
                {"id": q["id"], "verdict": "AGREE", "note": "Synthetic review fixture only"}
                for q in row["judgements"]
            ],
            note="Synthetic decision, not a real human review",
        )
        return review.decide(**{**self.common, "subject_id": "publisher", **args, **kwargs})


@override_settings(**SETTINGS)
class ReviewTests(ReviewFixture, TransactionTestCase):
    def test_pending_approved_rejected_versions_keep_hashes_judgements_and_history(self):
        first = self.propose()
        self.assertEqual(first["state"], "PENDING")
        self.assertEqual(EvaluationDecision.objects.count(), 0)
        self.assertEqual(self.decision(first)["state"], "APPROVE")
        changed = copy.deepcopy(self.bundle)
        changed["queries"][0]["expected"] = ["plain", "hamza", "intro"]
        second = self.propose(1, changed)
        self.assertEqual(first["corpus_sha256"], second["corpus_sha256"])
        self.assertNotEqual(first["judgements_sha256"], second["judgements_sha256"])
        self.assertEqual(second["state"], "PENDING")
        self.decision(second, action="REJECT")
        history = review.history(**self.common)["versions"]
        self.assertEqual([r["state"] for r in history], ["REJECT", "APPROVE"])
        self.assertEqual(history[1]["judgements"], first["judgements"])
        for operation in (
            lambda: EvaluationRevision.objects.filter(pk=first["id"]).update(note="changed"),
            lambda: EvaluationDecision.objects.filter(revision_id=first["id"]).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_exact_digests_independent_current_reviewer_and_all_judgements_required(self):
        row = self.propose()
        for kwargs in (
            {"subject_id": "editor"},
            {"corpus_sha256": "0" * 64},
            {"judgements_sha256": "0" * 64},
            {"confirmed": False},
            {"reviews": []},
            {
                "reviews": [
                    {"id": q["id"], "verdict": "PENDING", "note": "not reviewed"}
                    for q in row["judgements"]
                ]
            },
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(cases.CaseConflict):
                self.decision(row, **kwargs)
        self.assertEqual(EvaluationDecision.objects.count(), 0)
        self.propose(1)
        with self.assertRaises(cases.CaseConflict):
            self.decision(row)
        self.assertEqual(EvaluationDecision.objects.count(), 0)

    def test_deny_unknown_authority_case_and_malformed_or_unauthorized_expectations(self):
        with (
            override_settings(FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.propose()
        for mutation in (
            lambda b: b.update(synthetic_only=False),
            lambda b: b["queries"][0].update(expected=["foreign"]),
            lambda b: b["records"].append(b["records"][0]),
            lambda b: b["queries"][0].update(expected=["hamza", "hamza"]),
        ):
            changed = copy.deepcopy(self.bundle)
            mutation(changed)
            with self.assertRaises(cases.CaseConflict):
                self.propose(bundle=changed)
        row = self.propose()
        other = cases.intake_case(
            original_question="Synthetic other case",
            source_event_id="review-other",
            requester_id="review-other",
            idempotency_key="review-other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.decision(
                row, case_id=other["case_id"], provider=ReviewDirectory([other["public_ref"]])
            )

    def test_authority_revocation_after_insert_rolls_back_decision(self):
        row = self.propose()
        create = EvaluationDecision.objects.create

        def revoke(**kw):
            result = create(**kw)
            self.review_authority.denied.add("APPROVE")
            return result

        from unittest.mock import patch

        with patch.object(EvaluationDecision.objects, "create", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.decision(row)
        self.assertEqual(EvaluationDecision.objects.count(), 0)
        self.assertEqual(review.history(**self.common)["versions"][0]["state"], "PENDING")

    def test_native_csrf_pending_form_and_default_denial(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        endpoint = "/casework/staff/"
        opening = dict(action="research_evaluation_open", case_ref=self.receipt["public_ref"])
        login = client.get("/casework/staff/login/")
        logged = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            login,
        )
        self.assertEqual(logged.status_code, 303)
        page = post(client, endpoint, opening, client.get(endpoint))
        self.assertContains(page, "لم يُنشأ إصدار")
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(client.post(endpoint, {"action": "propose"}).status_code, 403)
        created = post(
            client,
            endpoint,
            dict(
                action="research_evaluation_propose",
                case_ref=self.receipt["public_ref"],
                expected_number="0",
                bundle=json.dumps(self.bundle),
                note="Synthetic UI proposal",
            ),
            page,
        )
        self.assertContains(created, "بانتظار المراجعة")
        self.assertEqual(EvaluationDecision.objects.count(), 0)
        with override_settings(FATWA_ARABIC_SEARCH_REVIEW_ENABLED=False):
            self.assertEqual(post(client, endpoint, opening, created).status_code, 409)
