"""Native campaign forms, independent humans, exact previews and rollback."""

from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot
from tests.casework.test_http import hidden, post

from . import editor, services
from .models import IdentityMembership, IdentityObservation, Person, RegistryOperation
from .test_support import FEATURES, RegistryFixture


@override_settings(**FEATURES)
class IdentityRegistryHTTPTests(RegistryFixture, TransactionTestCase):
    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        name = {"editor": "editor", "other": "reviewer", "publisher": "publisher"}[subject]
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": f"synthetic-{name}-credential-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303, response.content)
        return client, client.get("/casework/staff/")

    def action(self, client, page, action="ir_open", **values):
        data = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "case_ref": self.receipt["public_ref"],
            "action": action,
            **values,
        }
        return client.post(
            "/casework/staff/",
            urlencode(data, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )

    def test_native_capture_proposal_independent_verify_and_explicit_revoke(self):
        client, home = self.login()
        page = self.action(client, home)
        self.assertEqual(page.status_code, 200, page.content)
        captured = self.action(client, page, "ir_capture", state=hidden(page, "state"))
        self.assertContains(captured, "غير مرتبطة")
        created = self.action(
            client,
            captured,
            "ir_person",
            state=hidden(captured, "state"),
            label="شخص اختبار الواجهة",
            reason="سجل بشري اختياري",
            confirmed="yes",
        )
        self.assertEqual(created.status_code, 200, created.content)
        person = Person.objects.get()
        identity = IdentityObservation.objects.get().identity_id
        proposed = self.action(
            client,
            created,
            "ir_propose",
            state=hidden(created, "state"),
            identity_id=str(identity),
            person_id=str(person.pk),
            evidence="سند بشري اصطناعي لا تشابه اسم",
            confirmed="yes",
        )
        self.assertContains(proposed, "بانتظار تحقق مستقل")
        self.assertNotContains(proposed, 'class="ir-verify"')
        reviewer, home = self.login("other")
        review_page = self.action(reviewer, home)
        from .models import LinkProposal

        proposal = LinkProposal.objects.get()
        reviewed = self.action(
            reviewer,
            review_page,
            "ir_decide",
            state=hidden(review_page, "state"),
            identity_id=str(identity),
            proposal_id=str(proposal.pk),
            kind="VERIFY",
            reason="تحقق مستقل موثق",
            confirmed="yes",
        )
        self.assertContains(reviewed, "ربط تحقّق منه إنسان مستقل")
        withdrawn = self.action(
            reviewer,
            reviewed,
            "ir_decide",
            state=hidden(reviewed, "state"),
            identity_id=str(identity),
            kind="UNLINK",
            reason="سحب التحقق بعد مراجعة السند",
            confirmed="yes",
        )
        self.assertContains(withdrawn, "غير مرتبطة")
        self.assertEqual(IdentityMembership.objects.count(), 2)
        self.assertEqual(
            list(RegistryOperation.objects.order_by("created_at").values_list("kind", flat=True)),
            ["VERIFY", "UNLINK"],
        )
        self.assertIn("no-store", withdrawn["Cache-Control"])
        self.assertIn("noindex", withdrawn["X-Robots-Tag"])

    def test_native_merge_preview_and_confirmation_then_split_selected_link(self):
        one, person_a = self.capture(), self.person("أول")
        self.link(one, person_a)
        _, base = self.new_case()
        two, person_b = self.capture(base), self.person("ثانٍ")
        self.link(two, person_b, base)
        client, home = self.login()
        page = self.action(client, home)
        prepared = self.action(
            client,
            page,
            "ir_prepare",
            state=hidden(page, "state"),
            kind="MERGE",
            source_person_id=person_b["id"],
            target_person_id=person_a["id"],
        )
        self.assertContains(prepared, 'id="ir-preview"')
        self.assertEqual(IdentityMembership.objects.count(), 2)
        applied = self.action(
            client,
            prepared,
            "ir_apply",
            state=hidden(prepared, "state"),
            preview=hidden(prepared, "preview"),
            reason="دمج بشري صريح",
            confirmed="yes",
        )
        self.assertEqual(applied.status_code, 200, applied.content)
        prepared = self.action(
            client,
            applied,
            "ir_prepare",
            state=hidden(applied, "state"),
            kind="SPLIT",
            source_person_id=person_a["id"],
            target_person_id=person_b["id"],
            identity_ids=[two["id"]],
        )
        self.assertEqual(prepared.status_code, 200, prepared.content)
        applied = self.action(
            client,
            prepared,
            "ir_apply",
            state=hidden(prepared, "state"),
            preview=hidden(prepared, "preview"),
            reason="تصحيح فصل موثق",
            confirmed="yes",
        )
        self.assertEqual(applied.status_code, 200, applied.content)
        self.assertEqual(RegistryOperation.objects.filter(kind="SPLIT").count(), 1)

    def test_csrf_cross_actor_and_stale_preview_are_rejected(self):
        client, home = self.login()
        page = self.action(client, home)
        self.assertEqual(
            client.post(
                "/casework/staff/", {"action": "ir_open", "case_ref": self.receipt["public_ref"]}
            ).status_code,
            403,
        )
        other, home2 = self.login("other")
        opened = self.action(other, home2)
        denied = self.action(
            other,
            opened,
            "ir_person",
            state=hidden(page, "state"),
            label="محاولة",
            reason="تبديل مستخدم",
            confirmed="yes",
        )
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(Person.objects.exists())
        command = hidden(page, "state")
        self.person("حدث لاحق")
        denied = self.action(client, page, "ir_capture", state=command)
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(IdentityObservation.objects.exists())

    def test_late_render_identity_revocation_rolls_back_whole_command(self):
        client, home = self.login()
        page = self.action(client, home)
        real = editor.render

        def revoke(*args, **kwargs):
            response = real(*args, **kwargs)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], active=False
            )
            return response

        with patch.object(editor, "render", side_effect=revoke):
            denied = self.action(
                client,
                page,
                "ir_person",
                state=hidden(page, "state"),
                label="لن يبقى",
                reason="اختبار ذرية الرد",
                confirmed="yes",
            )
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(Person.objects.exists())
        self.assertNotIn("لن يبقى".encode(), denied.content)

    def test_read_scope_excludes_hidden_identity_counts_and_missing_authority_denies(self):
        self.capture()
        receipt, base = self.new_case()
        self.capture(base)
        self.person("شخص مخفي", base)
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({self.receipt["public_ref"]})
        )
        client, home = self.login()
        page = self.action(client, home)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertNotContains(page, "شخص مخفي")
        self.assertNotContains(page, receipt["public_ref"])
        with override_settings(FATWA_IDENTITY_REGISTRY_AUTHORITY=None):
            self.assertEqual(self.action(client, page).status_code, 409)
        self.assertEqual(services.desk(**self.common)["identities"][0]["state"], "UNLINKED")

    def test_native_render_equal_directory_replacement_rolls_back_whole_command(self):
        from django.conf import settings

        class EqualDirectory(Directory):
            def __eq__(self, other):
                return True

        alternate = bind_identity_snapshot(EqualDirectory([self.receipt["public_ref"]]))
        alternate.identities = dict(self.directory.identities)
        self.assertEqual(alternate.projection_epoch(), self.directory.projection_epoch())
        client, home = self.login()
        page = self.action(client, home)
        real = editor.render

        def replace_after_render(*args, **kwargs):
            response = real(*args, **kwargs)
            settings.FATWA_CASEWORK_IDENTITY_PROVIDER = alternate
            return response

        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory),
            patch.object(editor, "render", side_effect=replace_after_render),
        ):
            denied = self.action(
                client,
                page,
                "ir_person",
                state=hidden(page, "state"),
                label="لا يخرج هذا السجل بعد تبديل المصدر",
                reason="اختبار تبديل كائن المصدر خلال توليد الرد",
                confirmed="yes",
            )
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(Person.objects.exists())
        self.assertNotIn("لا يخرج هذا السجل بعد تبديل المصدر".encode(), denied.content)
        self.assertEqual(self.action(client, page).status_code, 200)
