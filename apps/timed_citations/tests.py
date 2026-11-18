"""Synthetic PostgreSQL contracts, real canonical bytes and scoped native forms."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.core import signing
from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.experimental_publication.tests import Directory
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from .models import TimedCitation, TimedCitationAction
from .rights import TimedMediaRights
from .views import SALT

SETTINGS = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.timed_citations.urls",
    "MIDDLEWARE": [
        "apps.platform_recovery.middleware.MaintenanceGuard",
        "apps.timed_citations.guard.TimedCitationGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    "FATWA_TIMED_CITATIONS_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_SOURCE_RIGHTS_ENFORCED": True,
}


class ExactMediaRights(TimedMediaRights):
    def __init__(self, ref):
        self.ref = ref
        self.pins = set()
        self.actions = {"READ_MEDIA", "CITE"}
        self.valid_until = timezone.now() + timedelta(minutes=1)

    def permits(self, **kw):
        r = kw["resource"]
        return (
            kw["case_ref"] == self.ref
            and kw["provider_id"] == Directory.provider_id
            and kw["subject_id"] == "editor"
            and kw["auth_epoch"] == "epoch-1"
            and kw["action"] in self.actions
            and timezone.now() < self.valid_until
            and (r.kind, r.identifier, r.sha256) in self.pins
        )

    def grant_deadline(self, **kw):
        return self.valid_until if self.permits(**kw) else None


class Fixture:
    def setUp(self):
        super().setUp()
        self.receipt = cases.intake_case(
            original_question="PRIVATE synthetic question",
            source_event_id="timed-fixture",
            requester_id="synthetic-one",
            idempotency_key="timed-fixture",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory([self.receipt["public_ref"]])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.audio = audio_fixture()
        self.attachment = attachments.upload(
            token=self.receipt["token"],
            **self.audio,
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        self.save()
        self.part = AnswerPart.objects.get(kind="AUDIO")
        self.rights = ExactMediaRights(self.receipt["public_ref"])
        self.rights.pins = {
            ("ATTACHMENT", self.attachment["id"], self.attachment["sha256"]),
            ("ANSWER_MEDIA", str(self.part.pk), self.part.sha256),
        }
        overlay = override_settings(
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.pin = services.inspect_source(
            **self.common, kind="ATTACHMENT", source_id=self.attachment["id"]
        )

    def save(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return media.save_multipart_answer(
            **self.common,
            text="PRIVATE synthetic human answer",
            files=[self.audio],
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )

    def propose(self, **kw):
        case = Case.objects.get(pk=self.receipt["case_id"])
        args = dict(
            self.common,
            source_pin=self.pin,
            start_ms=0,
            end_ms=100,
            reason="PRIVATE exact human locator",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        return services.propose(**{**args, **kw})

    def confirm(self, row):
        return services.act(**self.common, citation_id=row["id"], action="CONFIRM", confirmed=True)

    def opened(self, row, **kw):
        return services.open_audio(**self.common, citation_id=row["id"], **kw)


@override_settings(**SETTINGS)
class TimedTests(Fixture, TransactionTestCase):
    def test_exact_duration_human_confirmation_and_original_bytes(self):
        self.assertEqual(self.pin["duration_ms"], 100)
        row = self.propose(start_ms=10, end_ms=90)
        with self.assertRaises(cases.CaseConflict):
            self.opened(row)
        self.assertEqual(self.opened(row, review=True)["raw"], self.audio["raw"])
        self.confirm(row)
        opened = self.opened(row)
        self.assertEqual(opened["raw"], self.audio["raw"])
        self.assertEqual((opened["start_ms"], opened["end_ms"]), (10, 90))
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(
            Case.objects.get(pk=self.receipt["case_id"]).source.original_question,
            "PRIVATE synthetic question",
        )
        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            rows = services.for_locked_answer(
                answer=case.answers.get(), actor=actor, provider=self.directory
            )
            self.assertEqual(rows[0]["source"]["sha256"], self.attachment["sha256"])

    def test_invalid_times_and_forged_duration_version_digest_are_denied(self):
        for start, end in (
            (-1, 5),
            (0, 0),
            (5, 4),
            (0, 101),
            (True, 50),
            (0, 1.5),
            (0, "5"),
            (float("nan"), 5),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(cases.CaseConflict):
                self.propose(start_ms=start, end_ms=end)
        for key, value in (
            ("duration_ms", 200),
            ("version", 999),
            ("version", True),
            ("sha256", "0" * 64),
            ("metadata_sha256", "f" * 64),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(cases.CaseConflict):
                self.propose(source_pin={**self.pin, key: value})
        self.assertEqual(TimedCitation.objects.count(), 0)

    def test_old_answer_does_not_inherit_citation_and_exact_old_recording_never_redirects(self):
        part_pin = services.inspect_source(
            **self.common, kind="ANSWER_MEDIA", source_id=str(self.part.pk)
        )
        row = self.propose(source_pin=part_pin)
        self.confirm(row)
        self.save()
        with self.assertRaises(cases.CaseConflict):
            self.opened(row)
        history = services.desk(**self.common)["history"][0]
        self.assertFalse(history["current"])
        self.assertEqual(history["source"]["id"], str(self.part.pk))
        # An explicit correction may deliberately cite the still-permitted old
        # recording; there is no silent pointer substitution to the new part.
        corrected = self.propose(source_pin=part_pin, replaces_id=row["id"], start_ms=5, end_ms=60)
        self.confirm(corrected)
        self.assertEqual(TimedCitation.objects.get(pk=corrected["id"]).part_id, self.part.pk)
        self.assertEqual(self.opened(corrected)["raw"], self.audio["raw"])

    def test_correction_is_append_only_and_previous_revision_cannot_open(self):
        first = self.propose()
        self.confirm(first)
        second = self.propose(
            replaces_id=first["id"], start_ms=20, end_ms=80, reason="Human correction"
        )
        with self.assertRaises(cases.CaseConflict):
            self.opened(first)
        self.confirm(second)
        self.assertEqual(self.opened(second)["start_ms"], 20)
        self.assertEqual(TimedCitation.objects.count(), 2)
        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            self.assertEqual(
                len(
                    services.for_locked_answer(
                        answer=case.answers.get(), actor=actor, provider=self.directory
                    )
                ),
                1,
            )
        for operation in (
            lambda: TimedCitation.objects.all().update(reason="erase"),
            lambda: TimedCitation.objects.all().delete(),
            lambda: TimedCitationAction.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_withdrawal_blocks_open_and_confirmation_without_erasing_history(self):
        row = self.propose()
        self.confirm(row)
        self.rights.actions.clear()
        services.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        with self.assertRaises(cases.CaseConflict):
            self.opened(row)
        with self.assertRaises(cases.CaseConflict):
            self.confirm(row)
        history = services.desk(**self.common)["history"][0]
        self.assertEqual(history["state"], "WITHDRAWN")
        self.assertIsNone(history["source"])
        self.assertEqual(history["reason"], "")
        self.assertEqual(AnswerRevision.objects.count(), 1)

    def test_read_media_does_not_imply_cite_and_expiry_hides_source_and_notes(self):
        row = self.propose()
        self.confirm(row)
        for action in ("READ_MEDIA", "CITE"):
            self.rights.actions.remove(action)
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)
            state = services.desk(**self.common)
            self.assertEqual(state["sources"], [])
            self.assertNotIn(self.pin["filename"], str(state))
            self.assertNotIn("PRIVATE exact human locator", str(state))
            self.rights.actions.add(action)
        with override_settings(
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(media_rights=self.rights)
        ):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)
        with patch.object(timezone, "now", return_value=timezone.now() + timedelta(minutes=2)):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)
            self.assertEqual(services.desk(**self.common)["sources"], [])

    def test_cross_case_and_revoked_identity_are_denied(self):
        row = self.propose()
        self.confirm(row)
        other = cases.intake_case(
            original_question="other",
            source_event_id="other",
            requester_id="other",
            idempotency_key="other",
            synthetic_fixtures_only=True,
        )
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({other["public_ref"]})
        )
        for operation in (
            lambda: self.opened(row),
            lambda: services.desk(**self.common),
            lambda: self.propose(),
        ):
            with self.assertRaises(cases.CaseConflict):
                operation()
        with self.assertRaises(cases.CaseConflict):
            services.inspect_source(
                **{**self.common, "case_id": other["case_id"]},
                kind="ATTACHMENT",
                source_id=self.attachment["id"],
            )

    def test_approved_answer_cannot_acquire_or_change_timed_citations(self):
        row = self.propose()
        self.confirm(row)  # Canonical approval now requires confirmed current locators.
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.record_decision(
            **self.common,
            answer_id=case.answers.get().pk,
            action="APPROVE",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        with self.assertRaises(cases.CaseConflict):
            self.confirm(row)
        with self.assertRaises(cases.CaseConflict):
            self.propose()
        with self.assertRaises(cases.CaseConflict):
            self.opened(row, review=True)
        services.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        self.assertIsNotNone(Case.objects.get(pk=self.receipt["case_id"]).approved_answer_id)

    def test_non_audio_missing_parser_proof_and_disabled_configuration_deny(self):
        text_part = AnswerPart.objects.get(kind="TEXT")
        with self.assertRaises(cases.CaseConflict):
            services.inspect_source(**self.common, kind="ANSWER_MEDIA", source_id=str(text_part.pk))
        with patch.object(services, "validate", side_effect=services.MediaValidationError("bad")):
            with self.assertRaises(cases.CaseConflict):
                self.propose()
        for config in (
            {"FATWA_TIMED_CITATIONS_ENABLED": False},
            {"FATWA_RESEARCH_WORKSPACE_RIGHTS": None},
            {"FATWA_SOURCE_RIGHTS_ENFORCED": "false"},
        ):
            with override_settings(**config), self.assertRaises(cases.CaseConflict):
                self.propose()

    def test_mid_read_identity_change_prevents_bytes_and_mutation(self):
        row = self.propose()
        self.confirm(row)
        original = services.validate

        def changed(*args):
            result = original(*args)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="changed"
            )
            return result

        with patch.object(services, "validate", side_effect=changed):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)
        self.assertEqual(TimedCitation.objects.count(), 1)

    def test_expiry_during_composition_rolls_back_write_and_denies_byte_response(self):
        real_now = timezone.now()
        clock = [real_now]
        original_identity = services._identity

        def expire(case, actor, provider):
            original_identity(case, actor, provider)
            clock[0] = real_now + timedelta(minutes=2)

        with (
            patch.object(timezone, "now", side_effect=lambda: clock[0]),
            patch.object(services, "_identity", side_effect=expire),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.propose()
        self.assertEqual(TimedCitation.objects.count(), 0)
        row = self.propose()
        self.confirm(row)
        original = services._rights
        count = [0]

        def rights_then_expire(*args):
            original(*args)
            count[0] += 1
            if count[0] == 3:
                clock[0] = real_now + timedelta(minutes=2)

        clock[0] = real_now
        with (
            patch.object(timezone, "now", side_effect=lambda: clock[0]),
            patch.object(services, "_rights", side_effect=rights_then_expire),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)

    def test_concurrent_correction_accepts_one_successor_only(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connections

        first = self.propose()

        def correct():
            try:
                return self.propose(replaces_id=first["id"])["state"]
            except cases.CaseConflict:
                return "CONFLICT"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(
                list(pool.map(lambda _: correct(), range(2))), ["PROPOSED", "CONFLICT"]
            )
        self.assertEqual(TimedCitation.objects.count(), 2)

    def test_database_rejects_cross_case_snapshot_owner_and_forged_duration(self):
        row = self.propose()
        original = TimedCitation.objects.get(pk=row["id"])
        values = {
            f.name: getattr(original, f.name)
            for f in TimedCitation._meta.fields
            if f.name not in {"id", "series", "number", "previous", "created_at"}
        }
        for changes in (
            {"snapshot": {**original.snapshot, "sha256": "0" * 64}},
            {"snapshot": {**original.snapshot, "duration_ms": 101}, "duration_ms": 101},
            {"start_ms": 100, "end_ms": 101},
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                TimedCitation.objects.create(**{**values, **changes}, number=1)
        other = cases.intake_case(
            original_question="other",
            source_event_id="db-other",
            requester_id="other",
            idempotency_key="db-other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TimedCitation.objects.create(
                **{**values, "case": Case.objects.get(pk=other["case_id"])}, number=1
            )

    def test_correction_note_cannot_reveal_revoked_previous_recording(self):
        first = self.propose()
        pin = services.inspect_source(
            **self.common, kind="ANSWER_MEDIA", source_id=str(self.part.pk)
        )
        second = self.propose(
            source_pin=pin, replaces_id=first["id"], reason="PRIVATE previous recording detail"
        )
        self.confirm(second)
        self.rights.pins.remove(("ATTACHMENT", self.attachment["id"], self.attachment["sha256"]))
        history = services.desk(**self.common)["history"]
        self.assertNotIn("PRIVATE previous recording detail", str(history))
        current = next(r for r in history if r["id"] == second["id"])
        self.assertIsNotNone(current["source"])
        self.assertEqual(current["reason"], "")
        self.assertEqual(self.opened(second)["raw"], self.audio["raw"])

    def test_browser_capture_contract_uses_actual_pcm_duration_and_exact_owner_version(self):
        import io
        import wave
        from hashlib import sha256

        previous = None
        for kind, frames in (("ATTACHMENT", 7001), ("ANSWER_MEDIA", 80000)):
            output = io.BytesIO()
            with wave.open(output, "wb") as sound:
                sound.setnchannels(1)
                sound.setsampwidth(2)
                sound.setframerate(8000)
                sound.writeframes(b"\x01\x00" * frames)
            capture = {
                "raw": output.getvalue(),
                "filename": "capture.wav",
                "media_type": "audio/wav",
            }
            self.assertEqual(len(capture["raw"]), 44 + frames * 2)
            if kind == "ATTACHMENT":
                case = Case.objects.get(pk=self.receipt["case_id"])
                owner = attachments.upload(
                    token=self.receipt["token"],
                    **capture,
                    expected_revision=case.revision,
                    synthetic_fixtures_only=True,
                )
            self.audio = capture
            self.save()
            case = Case.objects.get(pk=self.receipt["case_id"])
            if kind == "ANSWER_MEDIA":
                part = AnswerPart.objects.get(
                    manifest__answer__case=case,
                    manifest__answer__revision=case.answer_revision,
                    kind="AUDIO",
                )
                owner = {"id": str(part.pk), "sha256": part.sha256}
            self.rights.pins.add((kind, owner["id"], owner["sha256"]))
            pin = services.inspect_source(**self.common, kind=kind, source_id=owner["id"])
            self.assertEqual(pin["duration_ms"], frames * 1000 // 8000)
            self.assertEqual(
                pin["version"],
                case.evidence_version if kind == "ATTACHMENT" else case.answer_revision,
            )
            self.assertEqual(pin["sha256"], sha256(capture["raw"]).hexdigest())
            with self.assertRaises(cases.CaseConflict):
                self.propose(source_pin=pin, end_ms=pin["duration_ms"] + 1)
            row = self.propose(source_pin=pin, end_ms=pin["duration_ms"])
            self.confirm(row)
            self.assertEqual(self.opened(row)["raw"], capture["raw"])
            if previous:
                with self.assertRaises(cases.CaseConflict):
                    self.opened(previous)
            previous = row

    def test_native_http_csrf_scope_player_and_private_bytes(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        desk = {"action": "timed_desk", "case_ref": self.receipt["public_ref"]}
        self.assertEqual(client.post("/casework/staff/", desk).status_code, 403)
        page = client.get("/casework/staff/login/")
        page = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        page = client.get("/casework/staff/")
        page = post(client, "/casework/staff/", desk, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "100 مللي ثانية")
        page = post(
            client,
            "/casework/staff/",
            {
                "action": "timed_propose",
                "case_ref": self.receipt["public_ref"],
                "source_pin": signing.dumps(self.pin, salt=SALT),
                "start_ms": "10",
                "end_ms": "90",
                "reason": "Synthetic chosen segment",
                "replaces_id": "",
                "revision": "3",
                "evidence_version": "2",
            },
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        row = TimedCitation.objects.get()
        player = {
            "action": "timed_preview",
            "case_ref": self.receipt["public_ref"],
            "citation_id": str(row.pk),
        }
        page = post(client, "/casework/staff/", player, page)
        self.assertContains(page, "#t=0.01,0.09")
        review_url = f"/casework/staff/timed-citations/{row.pk}/review-audio/"
        self.assertEqual(client.get(review_url).content, self.audio["raw"])
        url = f"/casework/staff/timed-citations/{row.pk}/audio/"
        self.assertEqual(client.get(url).status_code, 404)
        self.confirm({"id": str(row.pk)})
        response = client.get(url)
        self.assertEqual(response.content, self.audio["raw"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(client.get(url, REMOTE_ADDR="192.0.2.1").status_code, 403)
        self.assertEqual(client.get(url, HTTP_X_FORWARDED_FOR="127.0.0.1").status_code, 403)
        self.assertEqual(
            Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1").get(url).status_code, 404
        )
        self.rights.actions.clear()
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.head(url).status_code, 404)
