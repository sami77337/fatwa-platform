"""Synthetic PostgreSQL contracts for human assignments and connected workload views."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlencode

from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import CaseEvent
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import services
from .models import AssignmentEvent


class Directory(MuftiIdentityProvider):
    provider_id = "assignment-fixture-directory"

    def __init__(self, refs):
        self.identities = {
            subject: MuftiIdentity(
                subject,
                "MUFTI",
                True,
                frozenset(refs),
                "epoch-1",
                timezone.now() + timedelta(minutes=30),
            )
            for subject in ("mufti-a", "mufti-b", "mufti-c")
        }
        self.credentials = {
            subject: letter * 64
            for subject, letter in (
                ("mufti-a", "A"),
                ("mufti-b", "B"),
                ("mufti-c", "C"),
            )
        }

    def authenticate(self, credential):
        subject = next(
            (key for key, value in self.credentials.items() if value == credential), None
        )
        return self.identities.get(subject)

    def resolve(self, subject_id):
        return self.identities.get(subject_id)


class AssignmentFixture:
    def setUp(self):
        self.receipt = self.intake("original")
        self.directory = Directory([self.receipt["public_ref"]])
        self.identity_settings = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.identity_settings.enable()
        self.addCleanup(self.identity_settings.disable)

    def intake(self, name):
        return cases.intake_case(
            original_question=f"PRIVATE SYNTHETIC {name}",
            requester_id="assignment-requester-" + name,
            source_event_id="assignment-event-" + name,
            idempotency_key="assignment-" + name,
            synthetic_fixtures_only=True,
        )

    def common(self, actor="mufti-a", receipt=None):
        receipt = receipt or self.receipt
        return {
            "case_id": receipt["case_id"],
            "subject_id": actor,
            "provider": self.directory,
            "synthetic_fixtures_only": True,
        }

    def grant_all(self, *receipts):
        refs = frozenset(row["public_ref"] for row in (self.receipt, *receipts))
        for subject, identity in self.directory.identities.items():
            self.directory.identities[subject] = replace(identity, case_keys=refs)

    def change(self, action, *, actor="mufti-a", version=0, target=None, receipt=None, **overrides):
        common = self.common(actor, receipt)
        current = cases.read_case(**common)
        return services.change_assignment(
            **common,
            action=action,
            expected_assignment_version=version,
            target_subject=target,
            **{
                "expected_revision": current["revision"],
                "expected_evidence_version": current["evidence_version"],
                **overrides,
            },
        )

    def approved(self, receipt=None):
        common = self.common(receipt=receipt)
        current = cases.read_case(**common)
        answer = cases.save_answer(
            **common,
            text="جواب اصطناعي محفوظ",
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        return cases.record_decision(
            **common,
            action="APPROVE",
            answer_id=answer["answers"][-1]["id"],
            note="",
            expected_revision=answer["revision"],
            expected_evidence_version=answer["evidence_version"],
        )


@override_settings(FATWA_CASE_ASSIGNMENTS_ENABLED=True, FATWA_CASE_ASSIGNMENT_CANDIDATES=None)
class AssignmentServiceTests(AssignmentFixture, TransactionTestCase):
    def test_default_closed_and_explicit_synthetic_guard(self):
        with (
            override_settings(FATWA_CASE_ASSIGNMENTS_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.change("CLAIM")
        with self.assertRaises(cases.CaseConflict):
            services.read_assignment(**{**self.common(), "synthetic_fixtures_only": False})
        self.assertEqual(AssignmentEvent.objects.count(), 0)

    def test_claim_retry_release_preserve_case_facts_answer_and_approval(self):
        approved = self.approved()
        case_events = list(CaseEvent.objects.values_list("id", flat=True))
        claimed = self.change("CLAIM")
        self.assertEqual((claimed["version"], claimed["primary_subject"]), (1, "mufti-a"))
        retry = self.change("CLAIM")
        self.assertEqual(retry["version"], 1)
        released = self.change("RELEASE", version=1)
        self.assertEqual(released["version"], 2)
        self.assertTrue(released["is_shared"])
        self.assertEqual(cases.read_case(**self.common()), approved)
        self.assertEqual(list(CaseEvent.objects.values_list("id", flat=True)), case_events)
        self.assertEqual(AssignmentEvent.objects.count(), 2)

    def test_two_concurrent_claims_have_one_primary_and_one_immutable_event(self):
        ready = Barrier(2)

        def claim(actor):
            close_old_connections()
            try:
                ready.wait(timeout=5)
                try:
                    services.change_assignment(
                        **self.common(actor),
                        action="CLAIM",
                        expected_assignment_version=0,
                        expected_revision=1,
                        expected_evidence_version=1,
                    )
                    return "accepted"
                except cases.CaseConflict:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(claim, ["mufti-a", "mufti-b"]))
        self.assertCountEqual(results, ["accepted", "conflict"])
        events = list(AssignmentEvent.objects.all())
        self.assertEqual(len(events), 1)
        state = services.read_assignment(**self.common())
        self.assertEqual(state["primary_subject"], events[0].subject_id)
        self.assertEqual(state["version"], 1)

    def test_sql_rejects_concurrent_primary_inserts_even_without_service_preflight(self):
        ready = Barrier(2)

        def insert(actor):
            close_old_connections()
            try:
                event = AssignmentEvent(
                    case_id=self.receipt["case_id"],
                    sequence=1,
                    action="CLAIM",
                    target_subject=actor,
                    subject_id=actor,
                    provider_id=self.directory.provider_id,
                    auth_epoch="epoch-1",
                    case_revision=1,
                    evidence_version=1,
                    previous_sha256=services.ZERO_HASH,
                )
                event.sha256 = services._digest(event)
                ready.wait(timeout=5)
                try:
                    with transaction.atomic():
                        event.save(force_insert=True)
                    return "accepted"
                except IntegrityError:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(insert, ["mufti-a", "mufti-b"]))
        self.assertCountEqual(results, ["accepted", "rejected"])
        event = AssignmentEvent.objects.get()
        self.assertGreater(event.transaction_id, 0)
        state = services.read_assignment(**self.common())
        self.assertEqual(state["primary_subject"], event.subject_id)

    def test_transfer_requires_server_candidate_policy_and_current_target_scope(self):
        self.change("CLAIM")
        with self.assertRaises(cases.CaseConflict):
            self.change("TRANSFER", version=1, target="mufti-b")
        with override_settings(FATWA_CASE_ASSIGNMENT_CANDIDATES=lambda actor, ref: ["mufti-b"]):
            state = self.change("TRANSFER", version=1, target="mufti-b")
        self.assertEqual((state["version"], state["primary_subject"]), (2, "mufti-b"))
        with self.assertRaises(cases.CaseConflict):
            self.change("RELEASE", version=2)
        state = self.change("RELEASE", actor="mufti-b", version=2)
        self.assertTrue(state["is_shared"])

    def test_contributors_reviewers_role_change_removal_and_no_exclusive_edit_lock(self):
        self.change("CLAIM")
        with override_settings(FATWA_CASE_ASSIGNMENT_CANDIDATES=lambda actor, ref: ["mufti-b"]):
            state = self.change("ADD_CONTRIBUTOR", version=1, target="mufti-b")
        self.assertEqual(state["participants"][0]["role"], "CONTRIBUTOR")
        state = self.change("ADD_REVIEWER", actor="mufti-b", version=2, target="mufti-b")
        self.assertEqual(state["participants"][0]["role"], "REVIEWER")
        # Coordination does not remove the existing scope of another Mufti.
        answer = cases.save_answer(
            **self.common("mufti-b"),
            text="عمل بشري مخول",
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.assertEqual(answer["revision"], 2)
        self.change("REMOVE_PARTICIPANT", actor="mufti-b", version=3, target="mufti-b")
        state = services.read_assignment(**self.common("mufti-b"))
        self.assertFalse(state["is_mine"])
        self.assertEqual(state["primary_subject"], "mufti-a")
        self.assertEqual(state["participants"], [])

    def test_foreign_scope_inactive_or_non_mufti_candidate_never_gets_assignment(self):
        self.change("CLAIM")
        original = self.directory.identities["mufti-b"]
        for replacement in (
            replace(original, case_keys=frozenset({"foreign-case"})),
            replace(original, active=False),
            replace(original, role="ORGANIZER"),
        ):
            self.directory.identities["mufti-b"] = replacement
            with override_settings(FATWA_CASE_ASSIGNMENT_CANDIDATES=lambda actor, ref: ["mufti-b"]):
                with self.assertRaises(cases.CaseConflict):
                    self.change("TRANSFER", version=1, target="mufti-b")
            with self.assertRaises(cases.CaseConflict):
                services.read_assignment(**self.common("mufti-b"))
        self.assertEqual(AssignmentEvent.objects.count(), 1)

    def test_unlisted_target_and_browser_shaped_candidate_list_fail_closed(self):
        self.change("CLAIM")
        for configured in (
            None,
            "mufti-b",
            lambda actor, ref: {"mufti-b": "MUFTI"},
            lambda actor, ref: ["mufti-c"],
            lambda actor, ref: ["mufti-b", "mufti-b"],
        ):
            with override_settings(FATWA_CASE_ASSIGNMENT_CANDIDATES=configured):
                with self.assertRaises(cases.CaseConflict):
                    self.change("TRANSFER", version=1, target="mufti-b")
        self.assertEqual(AssignmentEvent.objects.count(), 1)

    def test_target_revocation_during_commit_rolls_back_new_event(self):
        self.change("CLAIM")
        calls = 0

        def candidates(actor, ref):
            nonlocal calls
            calls += 1
            if calls == 3:
                identity = self.directory.identities["mufti-b"]
                self.directory.identities["mufti-b"] = replace(identity, active=False)
            return ["mufti-b"]

        with override_settings(FATWA_CASE_ASSIGNMENT_CANDIDATES=candidates):
            with self.assertRaises(cases.CaseConflict):
                self.change("TRANSFER", version=1, target="mufti-b")
        self.assertEqual(AssignmentEvent.objects.count(), 1)

    def test_actor_epoch_change_after_insert_rolls_back_assignment(self):
        save = AssignmentEvent.save

        def revoke_after_insert(event, *args, **kwargs):
            result = save(event, *args, **kwargs)
            identity = self.directory.identities["mufti-a"]
            self.directory.identities["mufti-a"] = replace(identity, auth_epoch="epoch-2")
            return result

        with (
            patch.object(AssignmentEvent, "save", revoke_after_insert),
            self.assertRaises(cases.CaseConflict),
        ):
            self.change("CLAIM")
        self.assertEqual(AssignmentEvent.objects.count(), 0)

    def test_stale_assignment_case_or_evidence_versions_reject_without_mutation(self):
        self.change("CLAIM")
        self.change("RELEASE", version=1)
        with self.assertRaises(cases.CaseConflict):
            self.change("CLAIM", version=0)
        cases.add_followup(
            token=self.receipt["token"],
            text="تعقيب اصطناعي جديد",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.change("CLAIM", version=2, expected_revision=1, expected_evidence_version=1)
        with self.assertRaises(cases.CaseConflict):
            self.change("CLAIM", version=2, expected_evidence_version=1)
        self.assertEqual(AssignmentEvent.objects.count(), 2)

    def test_sql_guards_reject_mutation_forged_digest_sequence_and_second_primary(self):
        self.change("CLAIM")
        event = AssignmentEvent.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssignmentEvent.objects.filter(pk=event.pk).update(target_subject="mufti-b")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssignmentEvent.objects.filter(pk=event.pk).delete()
        for action, sequence, digest_override in (
            ("CLAIM", 2, None),
            ("RELEASE", 3, None),
            ("RELEASE", 2, "f" * 64),
        ):
            forged = AssignmentEvent(
                case_id=self.receipt["case_id"],
                sequence=sequence,
                action=action,
                target_subject="mufti-a",
                subject_id="mufti-a",
                provider_id=self.directory.provider_id,
                auth_epoch="epoch-1",
                case_revision=1,
                evidence_version=1,
                previous_sha256=event.sha256,
            )
            forged.sha256 = digest_override or services._digest(forged)
            with self.assertRaises(IntegrityError), transaction.atomic():
                forged.save(force_insert=True)
        self.assertEqual(AssignmentEvent.objects.count(), 1)

    def test_assignment_is_not_exposed_to_requester_and_scope_is_rechecked_on_reads(self):
        self.change("CLAIM")
        public = cases.requester_status(self.receipt["token"], synthetic_fixtures_only=True)
        self.assertNotIn("mufti-a", str(public))
        self.assertNotIn("assignment", str(public))
        identity = self.directory.identities["mufti-a"]
        self.directory.identities["mufti-a"] = replace(
            identity, case_keys=frozenset({"foreign-case"})
        )
        with self.assertRaises(cases.CaseConflict):
            services.read_assignment(**self.common())


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "apps.team_workspace.urls",
        "FATWA_CASE_ASSIGNMENTS_ENABLED": True,
        "FATWA_CASE_ASSIGNMENT_CANDIDATES": None,
    }
)
class AssignmentHTTPTests(AssignmentFixture, TransactionTestCase):
    def login(self, actor="mufti-a"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = post(
            client,
            "/casework/staff/login/",
            {
                "credential": self.directory.credentials[actor],
            },
            page,
        )
        self.assertEqual(response.status_code, 303)
        return client, client.get("/casework/staff/")

    def open_case(self, client, page, receipt=None):
        return post(
            client,
            "/casework/staff/",
            {
                "action": "open",
                "case_ref": (receipt or self.receipt)["public_ref"],
            },
            page,
        )

    def assignment(self, client, page, action, **extra):
        selected = page.context["selected"]
        return post(
            client,
            "/casework/staff/",
            {
                "action": action,
                "case_ref": selected["public_ref"],
                "revision": str(selected["revision"]),
                "evidence_version": str(selected["evidence_version"]),
                "assignment_version": str(page.context["assignment"]["version"]),
                **extra,
            },
            page,
        )

    def filter(self, client, page, inbox, **extra):
        return post(
            client,
            "/casework/staff/",
            {
                "action": "filter",
                "state": "all",
                "query": "",
                "sort": "newest",
                "inbox": inbox,
                **extra,
            },
            page,
        )

    def test_native_claim_mine_shared_release_and_other_scoped_actor_conflict(self):
        client, page = self.login()
        self.assertContains(page, "القضايا المشتركة غير المعينة")
        page = self.open_case(client, page)
        other_client, other_page = self.login("mufti-b")
        other_page = self.open_case(other_client, other_page)
        page = self.assignment(client, page, "assignment_claim")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'id="primary-mufti">mufti-a')
        conflict = self.assignment(other_client, other_page, "assignment_claim")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.context["assignment"]["primary_subject"], "mufti-a")
        self.assertNotContains(conflict, "نص المحاولة غير المحفوظة", status_code=409)
        mine = self.filter(client, page, "mine")
        self.assertContains(mine, self.receipt["public_ref"])
        shared = self.filter(client, mine, "shared")
        self.assertEqual(shared.context["rows"], [])
        page = self.open_case(client, shared)
        page = self.assignment(client, page, "assignment_release")
        shared = self.filter(client, page, "shared")
        self.assertContains(shared, self.receipt["public_ref"])
        self.assertEqual(AssignmentEvent.objects.count(), 2)
        self.assertEqual(CaseEvent.objects.count(), 1)

    @override_settings(ROOT_URLCONF="config.campaign_urls", FATWA_MUFTI_WORKSPACE_ENABLED=True)
    def test_assignment_panel_operates_inside_connected_mufti_case(self):
        client, page = self.login()
        page = post(
            client,
            "/casework/staff/",
            {
                "action": "case_workspace",
                "case_ref": self.receipt["public_ref"],
            },
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertTemplateUsed(page, "mufti_workspace/overview.html")
        page = self.assignment(client, page, "assignment_claim")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'id="primary-mufti">mufti-a')
        self.assertContains(page, "PRIVATE SYNTHETIC original")
        self.assertEqual(page.context["mufti_workspace"]["case"]["revision"], 1)

    def test_native_transfer_contribution_and_reviewer_metadata(self):
        client, page = self.login()
        page = self.open_case(client, page)
        page = self.assignment(client, page, "assignment_claim")
        with override_settings(
            FATWA_CASE_ASSIGNMENT_CANDIDATES=lambda actor, ref: ["mufti-b", "mufti-c"]
        ):
            page = self.assignment(client, page, "assignment_contributor", target_subject="mufti-b")
            self.assertEqual(page.status_code, 200)
            page = self.assignment(client, page, "assignment_reviewer", target_subject="mufti-c")
            self.assertEqual(page.status_code, 200)
            page = self.assignment(client, page, "assignment_transfer", target_subject="mufti-b")
            self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["assignment"]["primary_subject"], "mufti-b")
        self.assertEqual(
            [(r["subject_id"], r["role"]) for r in page.context["assignment"]["participants"]],
            [("mufti-c", "REVIEWER")],
        )
        self.assertEqual(CaseEvent.objects.count(), 1)

    def test_followup_drafts_review_and_approved_views_share_exact_case_scope(self):
        draft = self.intake("draft")
        approved = self.intake("approved")
        inaccessible = self.intake("hidden")
        self.grant_all(draft, approved)
        cases.add_followup(
            token=self.receipt["token"],
            text="New facts",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        cases.save_answer(
            **self.common(receipt=draft),
            text="مسودة محفوظة",
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.approved(approved)
        client, page = self.login()
        before = (CaseEvent.objects.count(), AssignmentEvent.objects.count())
        for inbox, expected in (
            ("followups", self.receipt),
            ("drafts", draft),
            ("review", draft),
            ("approved", approved),
        ):
            response = self.filter(client, page, inbox)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(
                [r["public_ref"] for r in response.context["rows"]], [expected["public_ref"]]
            )
            self.assertNotContains(response, inaccessible["public_ref"])
            self.assertNotContains(response, "PRIVATE SYNTHETIC")
            self.assertEqual(response.context["total"], 3)
        counts = {row["key"]: row["count"] for row in response.context["inboxes"]}
        self.assertEqual(
            counts,
            {
                "all": 3,
                "mine": 0,
                "shared": 3,
                "followups": 1,
                "drafts": 1,
                "review": 1,
                "approved": 1,
            },
        )
        narrowed = self.filter(client, page, "followups", query=draft["public_ref"])
        self.assertEqual(narrowed.context["rows"], [])
        self.assertEqual({row["key"]: row["count"] for row in narrowed.context["inboxes"]}, counts)
        self.assertEqual((CaseEvent.objects.count(), AssignmentEvent.objects.count()), before)

    def test_saving_current_answer_resolves_new_followup_view_without_false_read_claim(self):
        self.approved()
        current = cases.read_case(**self.common())
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع إضافية",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        client, page = self.login()
        changed = self.filter(client, page, "followups")
        self.assertEqual(len(changed.context["rows"]), 1)
        current = cases.read_case(**self.common())
        cases.save_answer(
            **self.common(),
            text="جواب على الوقائع الجديدة",
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        changed = self.filter(client, changed, "followups")
        self.assertEqual(changed.context["rows"], [])
        drafts = self.filter(client, changed, "drafts")
        self.assertEqual(len(drafts.context["rows"]), 1)

    def test_approved_view_orders_by_decision_time_and_supports_oldest(self):
        newer_case = self.intake("newer")
        self.grant_all(newer_case)
        self.approved(newer_case)
        self.approved(self.receipt)
        client, page = self.login()
        recent = self.filter(client, page, "approved")
        self.assertEqual(
            [r["public_ref"] for r in recent.context["rows"]],
            [self.receipt["public_ref"], newer_case["public_ref"]],
        )
        oldest = self.filter(client, page, "approved", sort="oldest")
        self.assertEqual(
            [r["public_ref"] for r in oldest.context["rows"]],
            [newer_case["public_ref"], self.receipt["public_ref"]],
        )

    def test_closed_flag_forged_fields_duplicates_csrf_and_foreign_case_are_rejected(self):
        client, page = self.login()
        page = self.open_case(client, page)
        with override_settings(FATWA_CASE_ASSIGNMENTS_ENABLED=False):
            self.assertEqual(self.assignment(client, page, "assignment_claim").status_code, 400)
            self.assertEqual(self.filter(client, page, "mine").status_code, 400)
        for extra in (
            {"role": "MUFTI"},
            {"target_subject": "mufti-b"},
            {"assignment_version": "-1"},
        ):
            self.assertEqual(
                self.assignment(client, page, "assignment_claim", **extra).status_code, 400
            )
        values = {
            "action": "assignment_claim",
            "case_ref": self.receipt["public_ref"],
            "revision": "1",
            "evidence_version": "1",
            "assignment_version": "0",
        }
        response = client.post(
            "/casework/staff/", urlencode(values), content_type="application/x-www-form-urlencoded"
        )
        self.assertEqual(response.status_code, 403)
        values["csrfmiddlewaretoken"] = hidden(page, "csrfmiddlewaretoken")
        response = client.post(
            "/casework/staff/",
            urlencode(values) + "&assignment_version=0",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 400)
        foreign = self.intake("out-of-scope")
        self.assertEqual(
            self.assignment(
                client, page, "assignment_claim", case_ref=foreign["public_ref"]
            ).status_code,
            403,
        )
        self.assertEqual(AssignmentEvent.objects.count(), 0)

    def test_legacy_filter_without_new_fields_remains_compatible(self):
        client, page = self.login()
        result = post(
            client, "/casework/staff/", {"action": "filter", "state": "all", "query": ""}, page
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual((result.context["sort"], result.context["inbox"]), ("newest", "all"))
