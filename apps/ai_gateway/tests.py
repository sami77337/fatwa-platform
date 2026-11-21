"""Failure-first contracts: no external model, source corpus or generated ruling."""

import copy
import json
import uuid
from dataclasses import replace
from threading import Event
from time import monotonic
from unittest.mock import patch

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseDecision
from apps.precise_citations.boundary import seal
from apps.precise_citations.models import CitationSet
from apps.research_library.models import LibraryVersion

from . import services
from .models import CandidateBatch, GatewayOutcome, GatewayRun
from .test_support import FEATURES, GatewayFixture


@override_settings(**FEATURES)
class CitationGatewayTests(GatewayFixture, TransactionTestCase):
    def test_default_off_missing_task_authority_and_processing_grant_deny_before_provider(self):
        for setting, value in (
            ("FATWA_AI_GATEWAY_ENABLED", False),
            ("FATWA_AI_CITATION_CANDIDATES_ENABLED", False),
            ("FATWA_AI_GATEWAY_AUTHORITY", None),
            ("FATWA_AI_DISABLED_PROVIDERS", {"synthetic-citation-fixture"}),
        ):
            with self.subTest(setting=setting), override_settings(**{setting: value}):
                with self.assertRaises(cases.CaseConflict):
                    self.request()
        for kind in ("DRAFT_FRAGMENT", "LIBRARY"):
            self.gateway_authority.denied.add(("PROCESS_CONTEXT", kind))
            with self.assertRaises(cases.CaseConflict):
                self.request()
            self.gateway_authority.denied.clear()
        self.assertEqual(self.ai_provider.calls, [])
        self.assertEqual(GatewayRun.objects.count(), 0)

    def test_only_registered_task_and_strict_bounded_human_inputs_are_accepted(self):
        variants = (
            {"task": "WRITE_ANSWER"},
            {"query": "x" * 241},
            {"query": ""},
            {"start": True},
            {"end": 4001},
            {"selection": "EXTERNAL"},
            {"expected_revision": 99},
            {"synthetic_fixtures_only": False},
        )
        for change in variants:
            with self.subTest(change=change), self.assertRaises(cases.CaseConflict):
                self.request(**change)
        self.assertEqual(self.ai_provider.calls, [])
        self.assertEqual(GatewayRun.objects.count(), 0)

    def test_missing_provider_is_an_actual_audited_unavailable_state(self):
        with override_settings(FATWA_AI_CITATION_PROVIDER=None):
            row = self.request()
            self.assertEqual(row["status"], "PROVIDER_UNAVAILABLE")
        run = GatewayRun.objects.get()
        self.assertEqual((run.provider_key, run.model_id, run.model_version), ("", "", ""))
        self.assertEqual(GatewayOutcome.objects.get().status, "PROVIDER_UNAVAILABLE")
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_exact_bounded_candidates_are_derived_and_originals_remain_byte_identical(self):
        original = list(LibraryVersion.objects.values())
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            row = self.request()
            with services.read_boundary(**self.common, run_id=row["id"]) as result:
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["candidates"][0]["selected"], self.source_text[:12])
                self.assertEqual(result["candidates"][0]["pin"]["locator"]["start"], 0)
        call = self.ai_provider.calls[0]
        self.assertEqual(call.query, "عبارة محددة")
        self.assertEqual(call.source.text, self.source_text[:24])
        self.assertNotIn("case_id", repr(call))
        self.assertNotIn("سؤال خاص", repr(call))
        self.assertNotIn(self.answer_text, repr(call))
        self.assertEqual(list(LibraryVersion.objects.values()), original)
        self.assertEqual(
            (
                AnswerRevision.objects.count(),
                CaseDecision.objects.count(),
                CitationSet.objects.count(),
            ),
            (0, 0, 0),
        )
        self.assertEqual(
            (
                GatewayRun.objects.count(),
                GatewayOutcome.objects.count(),
                CandidateBatch.objects.count(),
            ),
            (1, 1, 1),
        )
        self.assertNotIn(self.source_text, GatewayRun.objects.get().canonical_payload)
        self.assertNotIn("عبارة محددة", GatewayRun.objects.get().canonical_payload)
        self.assertNotIn(self.source_text, CandidateBatch.objects.get().canonical_payload)

    def test_provider_failure_and_deadline_leave_the_core_editable_without_raw_error_leak(self):
        self.ai_provider.error = RuntimeError("private provider diagnostic <secret>")
        failed = self.request()
        self.assertEqual(failed["status"], "PROVIDER_FAILED")
        self.assertNotIn("private", GatewayOutcome.objects.get().canonical_payload)
        self.ai_provider.error = None
        with patch.object(services, "monotonic", side_effect=[100.0, 121.0]):
            expired = self.request()
        self.assertEqual(expired["status"], "PROVIDER_FAILED")
        saved = cases.save_answer(
            **self.common, text=self.answer_text, expected_revision=1, expected_evidence_version=1
        )
        self.assertEqual(saved["answers"][-1]["text"], self.answer_text)

    def test_adversarial_unknown_fabricated_ranges_and_freeform_rulings_are_rejected(self):
        valid = self.ai_provider.output()
        bad = [
            {"answer": "حكم مختلق", **valid},
            {"candidates": [{"source_id": str(uuid.uuid4()), "start": 0, "end": 12}]},
            {"candidates": [{"source_id": self.material["version_id"], "start": -1, "end": 12}]},
            {"candidates": [{"source_id": self.material["version_id"], "start": 0, "end": 25}]},
            {"candidates": [{"source_id": self.material["version_id"], "start": True, "end": 12}]},
            {"candidates": [{**valid["candidates"][0], "page": 622}]},
            {"candidates": valid["candidates"] * 6},
            {"candidates": valid["candidates"] * 2},
        ]
        for value in bad:
            self.ai_provider.raw = json.dumps(value).encode()
            with self.subTest(value=value):
                result = self.request()
                self.assertEqual(result["status"], "OUTPUT_REJECTED")
        for raw in (
            b'{"candidates":[],"candidates":[]}',
            b"not json",
            b"x" * 8193,
            b'{"candidates":NaN}',
        ):
            self.ai_provider.raw = raw
            self.assertEqual(self.request()["status"], "OUTPUT_REJECTED")
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_revocation_after_provider_never_persists_or_displays_candidates(self):
        hooks = (
            lambda: self.gateway_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY")),
            lambda: self.authority.denied.add("READ"),
            lambda: self.citation_authority.denied.add("CITE_SOURCE"),
            lambda: self.directory.identities.update(
                editor=replace(self.directory.identities["editor"], active=False)
            ),
        )
        initial_actor = self.directory.identities["editor"]
        for hook in hooks:
            self.ai_provider.hook = hook
            with self.assertRaises(cases.CaseConflict):
                self.request()
            self.assertEqual(CandidateBatch.objects.count(), 0)
            self.assertEqual(GatewayOutcome.objects.latest("created_at").status, "REVOKED")
            self.gateway_authority.denied.clear()
            self.authority.denied.clear()
            self.citation_authority.denied.clear()
            self.directory.identities["editor"] = initial_actor

    def test_task_and_provider_kill_switch_after_return_and_current_reads(self):
        for setting, value in (
            ("FATWA_AI_GATEWAY_ENABLED", False),
            ("FATWA_AI_CITATION_CANDIDATES_ENABLED", False),
            ("FATWA_AI_DISABLED_PROVIDERS", {"synthetic-citation-fixture"}),
        ):
            change = override_settings(**{setting: value})
            self.ai_provider.hook = change.enable
            try:
                with self.assertRaises(cases.CaseConflict):
                    self.request()
            finally:
                change.disable()
        self.ai_provider.hook = None
        row = self.request()
        self.gateway_authority.denied.add(("PROCESS_CONTEXT", "DRAFT_FRAGMENT"))
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=row["id"]):
                self.fail("revoked candidate displayed")

    def test_render_and_human_selection_callbacks_cannot_return_after_revocation(self):
        row = self.request()
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=row["id"]) as result:
                self.assertTrue(result["candidates"])
                self.gateway_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY"))
        self.gateway_authority.denied.clear()
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=row["id"], selected_index=0):
                self.authority.denied.add("CITE")

    def test_retry_is_idempotent_but_a_key_cannot_change_query_actor_or_window(self):
        key = uuid.uuid4()
        first, second = self.request(request_key=key), self.request(request_key=key)
        self.assertEqual(first, second)
        self.assertEqual(len(self.ai_provider.calls), 1)
        for change in ({"query": "أخرى"}, {"end": 23}, {"subject_id": "other"}):
            with self.assertRaises(cases.CaseConflict):
                self.request(request_key=key, **change)
        self.assertEqual(GatewayRun.objects.count(), 1)

    def test_cross_actor_case_stale_version_and_changed_provider_cannot_read(self):
        row = self.request()
        for change in ({"subject_id": "other"}, {"case_id": uuid.uuid4()}):
            with self.assertRaises(cases.CaseConflict):
                with services.read_boundary(**{**self.common, **change}, run_id=row["id"]):
                    self.fail("cross boundary candidate read")
        self.ai_provider.spec = replace(self.ai_provider.spec, model_version="synthetic-fixture-v2")
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=row["id"]):
                self.fail("provider changed")

    def test_append_only_audit_rejects_raw_sql_mutation_and_invalid_payload(self):
        row = self.request()
        for model in (GatewayRun, GatewayOutcome, CandidateBatch):
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    model.objects.update(digest="0" * 64)
        copied = copy.copy(GatewayRun.objects.get())
        copied.id = uuid.uuid4()
        copied.request_key = uuid.uuid4()
        with self.assertRaises(IntegrityError), transaction.atomic():
            copied.save(force_insert=True)
        self.assertEqual(row["status"], "SUCCEEDED")

    def test_empty_output_is_honest_and_cannot_be_selected(self):
        self.ai_provider.raw = b'{"candidates":[]}'
        row = self.request()
        with services.read_boundary(**self.common, run_id=row["id"]) as result:
            self.assertEqual(result["candidates"], [])
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=row["id"], selected_index=0):
                self.fail("empty output produced an implicit candidate")

    def test_sql_rejects_sealed_null_ranges_and_invented_source_identity(self):
        self.request()
        original = GatewayRun.objects.get()
        variants = [copy.deepcopy(original.source) for _ in range(4)]
        variants[0]["locator"]["start"] = None
        variants[1]["kind"] = None
        variants[2]["id"] = str(uuid.uuid4())
        variants[3]["locator"]["end"] = True
        for source in variants:
            row = copy.copy(original)
            row.id, row.request_key, row.source = uuid.uuid4(), uuid.uuid4(), source
            with self.subTest(source=source), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    seal(row)

    def test_hung_provider_has_bounded_wait_single_slot_and_no_late_delivery(self):
        release = Event()
        self.ai_provider.hook = lambda: release.wait(timeout=2)
        key = uuid.uuid4()
        started = monotonic()
        try:
            with patch.object(services, "DEADLINE_SECONDS", 0.05):
                timed_out = self.request(request_key=key)
                self.assertLess(monotonic() - started, 1.0)
                self.assertEqual(timed_out["status"], "PROVIDER_FAILED")
                busy = self.request()
                self.assertEqual(busy["status"], "PROVIDER_FAILED")
            self.assertEqual(len(self.ai_provider.calls), 1)
            self.gateway_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY"))
        finally:
            release.set()
        from . import execution

        self.assertTrue(execution.SLOT.acquire(timeout=2))
        execution.SLOT.release()
        self.assertEqual(CandidateBatch.objects.count(), 0)
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=timed_out["id"]):
                self.fail("late result survived revocation")
        self.gateway_authority.denied.clear()
        self.ai_provider.hook = None
        self.assertEqual(self.request(request_key=key)["status"], "PROVIDER_FAILED")
        self.assertEqual(len(self.ai_provider.calls), 1)
        self.assertEqual(self.request()["status"], "SUCCEEDED")
        self.assertEqual(len(self.ai_provider.calls), 2)

    def test_model_identity_and_version_are_independently_audited_and_pinned(self):
        result = self.request()
        run = GatewayRun.objects.get()
        self.assertEqual(run.model_id, "synthetic-citation-model")
        self.assertEqual(run.model_version, "synthetic-ranges-v1")
        self.assertEqual(json.loads(run.canonical_payload)["model_id"], run.model_id)
        original = self.ai_provider.spec
        self.ai_provider.spec = replace(original, model_id="synthetic-other-model")
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=result["id"]):
                self.fail("same version on a different model was accepted")
        self.ai_provider.spec = original
        copied = copy.copy(run)
        copied.id, copied.request_key, copied.model_id = uuid.uuid4(), uuid.uuid4(), ""
        with self.assertRaises(IntegrityError), transaction.atomic():
            seal(copied)

    def test_forbidden_task_names_and_action_outputs_preserve_all_available_core_records(self):
        human = self.save_citations()
        self.review_citations(human)
        approved = cases.record_decision(
            **self.common,
            answer_id=human["answer_id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        labels = (
            "casework",
            "precise_citations",
            "identity_registry",
            "experimental_publication",
            "public_knowledge",
            "public_answer_media",
            "publication_destinations",
            "publication_schedules",
            "delivery_queue",
            "case_delivery_desk",
            "composite_delivery",
        )

        def snapshot():
            return {
                model._meta.label: list(model.objects.order_by("pk").values())
                for label in labels
                for model in django_apps.get_app_config(label).get_models()
            }

        before, identities = snapshot(), dict(self.directory.identities)
        self.assertTrue(before["casework.CaseSource"])
        self.assertTrue(before["casework.AnswerRevision"])
        self.assertTrue(before["casework.CaseDecision"])
        self.assertTrue(before["precise_citations.CitationSet"])
        for task in (
            "Answer Fatwa",
            "Draft Fatwa",
            "ANSWER_FATWA",
            "DRAFT_FATWA",
            "REWRITE_QUESTION",
            "COMPLETE_ANSWER",
            "APPROVE",
            "PUBLISH",
            "DELIVER",
            "MERGE_IDENTITY",
            "CHANGE_PERMISSIONS",
        ):
            with self.subTest(task=task), self.assertRaises(cases.CaseConflict):
                self.request(task=task, expected_revision=approved["revision"])
        self.assertEqual(self.ai_provider.calls, [])
        self.assertEqual(GatewayRun.objects.count(), 0)
        self.assertEqual(
            self.request(expected_revision=approved["revision"])["status"], "SUCCEEDED"
        )
        for field in (
            "answer",
            "draft",
            "ruling",
            "rewritten_question",
            "complete_answer",
            "approved",
            "publish",
            "deliver",
            "merge_identity",
            "permission_changes",
            "tool_calls",
        ):
            self.ai_provider.raw = json.dumps(
                {**self.ai_provider.output(), field: "untrusted instruction"}
            ).encode()
            with self.subTest(field=field):
                self.assertEqual(
                    self.request(expected_revision=approved["revision"])["status"],
                    "OUTPUT_REJECTED",
                )
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.directory.identities, identities)
        self.assertEqual(CandidateBatch.objects.count(), 1)
