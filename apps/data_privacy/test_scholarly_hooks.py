"""Private lesson metadata, exact source bytes and graph/search composition."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.research_library.test_support import bind_identity_snapshot
from apps.scholarly_links import services as links
from apps.scholarly_links import tests as fixture
from apps.scholarly_links import views
from apps.scholarly_links.models import SeriesVersion
from apps.source_case_intake import http_tests as source_fixture
from apps.source_case_intake import simulators
from tests.casework.test_http import Directory as SourceDirectory
from tests.casework.test_http import post

from . import services
from .authority import Grant
from .catalog import locate
from .test_support import Authority, PrivacyFixture


class ExactPrivacy:
    def privacy_on(self):
        bind_identity_snapshot(self.directory)
        self.privacy_policy, self.grants = Authority(), {}
        settings = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.privacy_policy,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.before_privacy = self.originals()

    def originals(self):
        return {
            label: list(apps.get_model(label).objects.order_by("pk").values())
            for label in (
                "casework.Case",
                "casework.CaseSource",
                "casework.CaseEvent",
                "casework.AnswerRevision",
                "casework.CaseDecision",
                "answer_media.AnswerManifest",
                "answer_media.AnswerPart",
                "scholarly_links.Lesson",
                "scholarly_links.LessonVersion",
                "scholarly_links.SeriesVersion",
                "scholarly_links.CaseLessonLink",
                "scholarly_links.CaseRelation",
                "scholarly_links.LinkDecision",
            )
        }

    def grant(self, target, action, *, previous=""):
        actor = self.directory.resolve("mufti-a")
        principal = services.staff_principal(self.directory, actor)
        values = dict(
            audience=principal.audience,
            provider_id=principal.provider_id,
            subject_id=principal.subject_id,
            auth_epoch=principal.auth_epoch,
            role=principal.role,
            case_ref=target.case_ref,
            target_kind=target.kind,
            target_id=target.identifier,
            source_digest=target.source_digest,
            classification="CONFIDENTIAL",
            previous_level=previous,
            action=action,
        )
        key = self.privacy_policy.key(values)
        self.privacy_policy.grants[key] = Grant(timezone.now() + timedelta(minutes=10))
        self.grants[(target.kind, target.identifier, action)] = key
        return key

    def admit(self, kind, identifier, *actions):
        target = locate(kind, identifier)
        if not services.history(target):
            self.grant(target, "CLASSIFY")
            services.classify(
                kind=kind,
                identifier=identifier,
                level="CONFIDENTIAL",
                note="تصنيف اصطناعي مستقل للمصدر أو النسخة؛ لا اعتماد علمي",
                expected_digest=services.ZERO,
                expected_source_digest=target.source_digest,
                request_key=uuid.uuid4(),
                provider=self.directory,
                subject_id="mufti-a",
                synthetic_fixtures_only=True,
            )
        return [self.grant(target, action) for action in actions]

    def admit_all(self):
        for kind, model in (
            ("CASE", "casework.Case"),
            ("ANSWER", "casework.AnswerRevision"),
            ("SERIES_VERSION", "scholarly_links.SeriesVersion"),
            ("LESSON_VERSION", "scholarly_links.LessonVersion"),
            ("ANSWER_PART", "answer_media.AnswerPart"),
        ):
            for identifier in (
                apps.get_model(model).objects.order_by("pk").values_list("pk", flat=True)
            ):
                self.admit(kind, identifier, "READ", "SEARCH")

    def deny(self, kind, identifier, action="READ"):
        self.privacy_policy.grants.pop(self.grants[(kind, str(identifier), action)])

    def assert_originals(self):
        self.assertEqual(self.originals(), self.before_privacy)

    def web(self):
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        login = self.client.get("/casework/staff/login/")
        self.assertEqual(
            post(
                self.client,
                "/casework/staff/login/",
                {"credential": self.directory.credentials["mufti-a"]},
                login,
            ).status_code,
            303,
        )
        self.page = self.client.get("/casework/staff/")

    def open_native(self):
        return post(
            self.client,
            "/casework/staff/",
            {"action": "scholarly_open", "case_ref": self.receipt["public_ref"]},
            self.page,
        )


@override_settings(**fixture.HTTP_FEATURES)
class ScholarlyPrivacyTests(ExactPrivacy, fixture.Fixture, TransactionTestCase):
    def test_case_read_and_search_filter_before_scope_choices_and_question_counts(self):
        self.privacy_on()
        self.assertEqual(self.search()["total"], 0)
        self.admit("CASE", self.receipt["case_id"], "READ")
        self.assertEqual(links.desk(**self.common())["case_ref"], self.receipt["public_ref"])
        result = self.search(query="PRIVATE-QUESTION")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["case_choices"], [])
        self.admit("CASE", self.receipt["case_id"], "SEARCH")
        result = self.search(query="PRIVATE-QUESTION")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["case_choices"], [self.receipt["public_ref"]])
        result.pop("_guard")  # Native rendering keeps this internal guard out of its DTO.
        self.assertNotIn(self.receipts[1]["public_ref"], repr(result))
        with self.assertRaises(cases.CaseConflict):
            self.search(related_case_ref=self.receipts[1]["public_ref"])
        self.assert_originals()

    def test_answer_text_requires_both_exact_read_and_search_before_matching(self):
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "READ", "SEARCH")
        answer = AnswerRevision.objects.get(case_id=self.receipt["case_id"])
        self.assertEqual(self.search(query="جواب بشري")["total"], 0)
        self.admit("ANSWER", answer.pk, "READ")
        self.assertEqual(self.search(query="جواب بشري")["total"], 0)
        self.admit("ANSWER", answer.pk, "SEARCH")
        self.assertEqual(self.search(query="جواب بشري")["total"], 1)
        self.deny("ANSWER", answer.pk)
        self.assertEqual(self.search(query="جواب بشري")["total"], 0)
        self.assertEqual(self.search(query="PRIVATE-QUESTION")["total"], 1)
        self.assertFalse(links.desk(**self.common())["has_answer"])
        self.assert_originals()

    def test_hidden_lesson_is_removed_before_positions_and_source_metadata(self):
        series, category = self.series(), self.category()
        first = self.lesson(series, category, title="مرئي أول")
        hidden = self.lesson(series, category, title="درس سري لا يدخل التعداد")
        last = self.lesson(series, category, title="مرئي أخير")
        self.review(self.link(first))
        self.privacy_on()
        self.admit_all()
        self.deny("LESSON_VERSION", hidden.pk)
        self.deny("ANSWER_PART", self.part.pk)
        result = links.desk(**self.common())
        self.assertEqual(
            [row["version_id"] for row in result["lessons"]], [str(first.pk), str(last.pk)]
        )
        self.assertEqual([row["position"] for row in result["lessons"]], [1, 2])
        self.assertTrue(
            all(not row["can_move_up"] and not row["can_move_down"] for row in result["lessons"])
        )
        self.assertNotIn(hidden.title, repr(result))
        self.assertEqual(result["parts"], [])
        self.assertIsNone(result["lesson_links"][0]["start_ms"])
        self.assertIsNone(result["lesson_links"][0]["end_ms"])
        for row in result["lessons"]:
            self.assertEqual(row["source"], {})
            self.assertFalse(row["source_available"])
            self.assertFalse(row["can_read_media"])
        self.assertNotIn(str(self.part.pk), repr(result["lessons"]))
        current = SeriesVersion.objects.filter(series=series.series).latest("number")
        self.deny("SERIES_VERSION", current.pk)
        self.assertEqual(links.desk(**self.common())["series"], [])
        self.assert_originals()

    def test_series_and_lesson_search_are_independent_of_reading_the_metadata(self):
        lesson = self.lesson()
        self.review(self.link(lesson))
        self.privacy_on()
        self.admit_all()
        self.assertEqual(self.search(lesson_id=lesson.lesson_id)["total"], 1)
        self.deny("LESSON_VERSION", lesson.pk, "SEARCH")
        self.assertEqual(
            links.read_lesson(**self.common(), lesson_version_id=lesson.pk)["title"], lesson.title
        )
        result = self.search()
        self.assertEqual(result["lessons"], [])
        self.assertEqual(result["categories"], [])
        with self.assertRaises(cases.CaseConflict):
            self.search(lesson_id=lesson.lesson_id)
        self.admit("LESSON_VERSION", lesson.pk, "SEARCH")
        self.deny("SERIES_VERSION", lesson.series_version_id, "SEARCH")
        self.assertEqual(self.search()["lessons"], [])
        self.admit("SERIES_VERSION", lesson.series_version_id, "SEARCH")
        self.assertEqual(self.search(lesson_id=lesson.lesson_id)["total"], 1)
        self.assert_originals()

    def test_manual_relation_and_target_choices_need_both_exact_answer_endpoints(self):
        relation = self.relation()
        self.review(relation)
        self.privacy_on()
        self.admit_all()
        self.assertEqual(len(links.desk(**self.common())["relations"]), 1)
        self.deny("ANSWER", relation.target_answer_id)
        result = links.desk(**self.common())
        self.assertEqual(result["relations"], [])
        self.assertNotIn(str(relation.target_answer_id), repr(result["targets"]))
        self.assertEqual(self.search(relation_kind="REFERRED_BY_SHEIKH")["total"], 0)
        self.admit("ANSWER", relation.target_answer_id, "READ")
        self.deny("ANSWER", relation.source_answer_id)
        self.assertEqual(links.desk(**self.common())["relations"], [])
        self.admit("ANSWER", relation.source_answer_id, "READ")
        self.assertEqual(len(links.desk(**self.common())["relations"]), 1)
        self.assert_originals()

    def test_history_does_not_expose_an_unclassified_or_denied_exact_version(self):
        first = self.lesson(title="نسخة قديمة خاصة")
        second = self.lesson(
            SeriesVersion.objects.get(pk=first.series_version_id),
            first.category,
            lesson_id=first.lesson_id,
            expected_lesson_version=first.number,
            title="نسخة أحدث متاحة",
        )
        self.privacy_on()
        self.admit_all()
        self.deny("LESSON_VERSION", first.pk)
        result = links.read_lesson(**self.common(), lesson_version_id=second.pk)
        self.assertEqual([row["id"] for row in result["history"]], [str(second.pk)])
        self.assertNotIn(first.title, repr(result))
        with self.assertRaises(services.PrivacyDenied):
            links.read_lesson(**self.common(), lesson_version_id=first.pk)
        self.admit("LESSON_VERSION", first.pk, "READ")
        self.assertEqual(
            len(links.read_lesson(**self.common(), lesson_version_id=second.pk)["history"]), 2
        )
        self.assert_originals()

    def test_source_audio_has_separate_admission_and_late_byte_revocation(self):
        lesson = self.lesson()
        self.privacy_on()
        self.admit_all()
        self.deny("ANSWER_PART", self.part.pk)
        with patch.object(links.media, "raw_for_part", wraps=links.media.raw_for_part) as reader:
            result = links.read_lesson(**self.common(), lesson_version_id=lesson.pk)
            self.assertFalse(result["source_available"])
            with self.assertRaises(services.PrivacyDenied):
                links.open_lesson_media(**self.common(), lesson_version_id=lesson.pk)
            reader.assert_not_called()
        self.admit("ANSWER_PART", self.part.pk, "READ")
        result = links.open_lesson_media(**self.common(), lesson_version_id=lesson.pk)
        self.assertTrue(result["raw"])
        original = links.media.raw_for_part
        reads = 0

        def read_then_revoke(*args, **kwargs):
            nonlocal reads
            raw = original(*args, **kwargs)
            if args[0].pk == self.part.pk:
                reads += 1
                if reads == 2:  # After admission/integrity, when the payload is assembled.
                    self.deny("ANSWER_PART", self.part.pk)
            return raw

        with patch.object(links.media, "raw_for_part", side_effect=read_then_revoke):
            with self.assertRaises(services.PrivacyDenied):
                links.open_lesson_media(**self.common(), lesson_version_id=lesson.pk)
        self.admit("ANSWER_PART", self.part.pk, "READ")
        self.assertEqual(
            links.open_lesson_media(**self.common(), lesson_version_id=lesson.pk)["raw"],
            result["raw"],
        )
        self.assert_originals()

    def test_last_native_domain_callback_discards_rendered_lesson_then_recovers(self):
        lesson = self.lesson(title="عنوان درس خاص لا يخرج بعد السحب")
        self.web()
        self.privacy_on()
        self.admit_all()
        armed = False
        render, permit = views.render, self.authority.permits
        key = self.grants[("LESSON_VERSION", str(lesson.pk), "READ")]

        def render_then_arm(*args, **kwargs):
            nonlocal armed
            response = render(*args, **kwargs)
            armed = True
            return response

        def last_callback(**values):
            allowed = permit(**values)
            if armed:
                self.privacy_policy.grants.pop(key, None)
            return allowed

        with (
            patch.object(views, "render", side_effect=render_then_arm),
            patch.object(self.authority, "permits", side_effect=last_callback),
        ):
            response = self.open_native()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(lesson.title.encode(), response.content)
        self.admit("LESSON_VERSION", lesson.pk, "READ")
        self.assertContains(self.open_native(), lesson.title)
        self.assert_originals()

    def test_privacy_permission_does_not_replace_existing_domain_read_authority(self):
        lesson = self.lesson()
        self.privacy_on()
        self.admit_all()
        self.authority.revoke("READ_LESSON", "LESSON")
        self.assertEqual(links.desk(**self.common())["lessons"], [])
        with self.assertRaises(cases.CaseConflict):
            links.read_lesson(**self.common(), lesson_version_id=lesson.pk)
        self.authority.denied.clear()
        self.assertEqual(
            links.read_lesson(**self.common(), lesson_version_id=lesson.pk)["title"], lesson.title
        )
        self.assert_originals()


@override_settings(**source_fixture.DESK_SETTINGS, FATWA_SCHOLARLY_LINKS_ENABLED=True)
class ScholarlySourceQuestionPrivacyTests(PrivacyFixture, TransactionTestCase):
    def setUp(self):
        self.receipt = source_fixture.receive(simulators.telegram())
        self.directory = SourceDirectory()
        self.directory.grant(self.receipt["public_ref"])
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.authority = Authority()
        settings = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
            # Plain question search never implies a lesson or link grant.
            FATWA_SCHOLARLY_LINKS_AUTHORITY=fixture.Authority([]),
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.target = locate("CASE", self.receipt["case_id"])

    def test_source_question_search_requires_its_own_receipt_search_permission(self):
        self.classify(self.target)
        self.allow(self.target, "CONFIDENTIAL", "READ")
        self.allow(self.target, "CONFIDENTIAL", "SEARCH")
        source = locate("SOURCE_RECEIPT", self.receipt["receipt_id"])
        self.classify(source)
        self.allow(source, "CONFIDENTIAL", "READ")
        common = dict(
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(links.search(**common, query="محفوظ كما ورد")["total"], 0)
        self.assertEqual(links.search(**common, query=self.receipt["public_ref"])["total"], 1)
        key = self.allow(source, "CONFIDENTIAL", "SEARCH")
        self.assertEqual(links.search(**common, query="محفوظ كما ورد")["total"], 1)
        del self.authority.grants[key]
        self.assertEqual(links.search(**common, query="محفوظ كما ورد")["total"], 0)
