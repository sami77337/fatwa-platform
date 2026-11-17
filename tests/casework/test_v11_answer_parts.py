"""Current-case native part selection uses the existing versioned answer service."""

from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services
from apps.answer_media import tests as fixtures
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from tests.casework.test_http import WEB_SETTINGS, hidden, post


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    }
)
class NativePartRevisionTests(TransactionTestCase):
    setUp = fixtures.AnswerMediaTests.setUp
    save = fixtures.AnswerMediaTests.save
    approve = fixtures.AnswerMediaTests.approve
    release = fixtures.AnswerMediaTests.release

    def open_editor(self):
        self.staff = Client(
            enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1"
        )
        page = self.staff.get("/casework/staff/login/")
        self.assertEqual(
            post(
                self.staff,
                "/casework/staff/login/",
                {"credential": self.directory.credential},
                page,
            ).status_code,
            303,
        )
        return post(
            self.staff,
            "/casework/staff/",
            {"action": "answer_media", "case_ref": self.receipt["public_ref"]},
            self.staff.get("/casework/staff/"),
        )

    def reorder(self, page, parts, **changes):
        fields = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "action": "answer_media_reorder",
            "case_ref": self.receipt["public_ref"],
            "revision": hidden(page, "revision"),
            "evidence_version": hidden(page, "evidence_version"),
            "parts": parts,
        }
        return self.staff.post(
            "/casework/staff/",
            urlencode({**fields, **changes}, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )

    def test_native_reorder_remove_preserves_originals_and_invalidates_release(self):
        self.save(
            files=[
                fixtures.audio_fixture(),
                {"raw": b"second synthetic", "filename": "second.txt", "media_type": "text/plain"},
                {"raw": b"third synthetic", "filename": "third.txt", "media_type": "text/plain"},
            ]
        )
        self.approve()
        self.release()
        before = services.staff_snapshot(**self.common)["latest_package"]
        original = [(p.pk, p.sha256, p.original) for p in AnswerPart.objects.all()]
        page = self.open_editor()
        self.assertContains(page, 'id="answer-part-order"')
        result = self.reorder(page, [before["parts"][3]["id"], "", before["parts"][1]["id"]])
        self.assertEqual(result.status_code, 200)
        current = services.staff_snapshot(**self.common)["latest_package"]
        self.assertEqual([p["filename"] for p in current["parts"][1:]], ["third.txt", "answer.wav"])
        self.assertFalse(current["approved"])
        self.assertNotEqual(current["answer_id"], before["answer_id"])
        for pk, digest, raw in original:
            old = AnswerPart.objects.get(pk=pk)
            self.assertEqual((old.sha256, old.original), (digest, raw))
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=self.receipt["token"],
                part_id=before["parts"][1]["id"],
                synthetic_fixtures_only=True,
            )

    def test_duplicate_empty_foreign_and_stale_selection_never_add_revision(self):
        self.save()
        page = self.open_editor()
        part = services.staff_snapshot(**self.common)["latest_package"]["parts"][1]["id"]
        before = cases.read_case(**self.common)["revision"]
        for values, code in (
            ([part, part], 409),
            ([""], 409),
            (["00000000-0000-0000-0000-000000000001"], 409),
            ([part] * 8, 400),
        ):
            self.assertEqual(self.reorder(page, values).status_code, code)
            self.assertEqual(cases.read_case(**self.common)["revision"], before)
        self.assertEqual(self.reorder(page, [part]).status_code, 200)
        saved = cases.read_case(**self.common)["revision"]
        self.assertEqual(self.reorder(page, [part]).status_code, 409)
        self.assertEqual(cases.read_case(**self.common)["revision"], saved)

    def test_reorder_requires_csrf_and_current_scope(self):
        self.save()
        page = self.open_editor()
        part = services.staff_snapshot(**self.common)["latest_package"]["parts"][1]["id"]
        self.assertEqual(self.reorder(page, [part], csrfmiddlewaretoken="").status_code, 403)
        from dataclasses import replace

        self.directory.current = replace(
            self.directory.current, case_keys=frozenset({"unrelated-case"})
        )
        self.assertEqual(self.reorder(page, [part]).status_code, 404)
