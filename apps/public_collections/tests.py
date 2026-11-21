"""Real PostgreSQL, cross-case scope, complete response boundaries and native forms."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent, CaseEvidence, CaseSource
from apps.research_library import services as library
from tests.casework.test_http import hidden

from . import editor, services, views
from .models import CollectionAction, CollectionRevision, CollectionSeries
from .test_support import FEATURES, CollectionFixture


def post(client, path, values):
    page = client.get("/casework/staff/")
    encoded = urlencode(
        {"csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"), **values}, doseq=True
    )
    return client.post(path, encoded, content_type="application/x-www-form-urlencoded")


@override_settings(**FEATURES)
class CollectionTests(CollectionFixture, TransactionTestCase):
    def originals(self):
        return [
            list(model.objects.order_by("pk").values())
            for model in (CaseSource, CaseEvidence, CaseEvent, AnswerRevision)
        ]

    def test_native_domain_journey_preserves_originals_and_requires_release(self):
        before = self.originals()
        row = self.create_collection()
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        for action in ("REVIEW", "APPROVE"):
            row = self.collection_action(row, action)
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        row = self.collection_action(row, "RELEASE")
        response = self.client.get(self.collection_url(row))
        self.assertContains(response, "مجموعة بشرية اصطناعية")
        self.assertContains(response, "عنوان تجريبي")
        for private in (
            "PRIVATE",
            self.receipt["public_ref"],
            self.receipt["case_id"],
            row["id"],
            "auth_epoch",
            "provider_id",
        ):
            self.assertNotContains(response, private)
        self.assertEqual(before, self.originals())
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("noindex", response["X-Robots-Tag"])

    def test_cross_case_topic_aggregates_exact_two_publications(self):
        second_case, second = self.second_publication()
        row = self.release_collection(
            self.create_collection(kind="TOPIC", members=[self.member(), self.member(second)])
        )
        response = self.client.get(self.collection_url(row))
        self.assertContains(response, "عنوان تجريبي")
        self.assertContains(response, "فتوى ثانية مصرح بها")
        self.assertNotContains(response, second_case["public_ref"])
        self.assertEqual(len(CollectionRevision.objects.get(pk=row["id"]).payload["members"]), 2)

    def test_missing_second_case_scope_rejects_save_without_partial_history(self):
        _, second = self.second_publication()
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({self.receipt["public_ref"]})
        )
        with self.assertRaises(cases.CaseConflict):
            self.create_collection(members=[self.member(), self.member(second)])
        self.assertEqual(CollectionSeries.objects.count(), 0)
        self.assertEqual(CollectionRevision.objects.count(), 0)

    def test_exact_member_grant_is_required_even_for_already_public_material(self):
        self.collections_authority.denied.add(("READ_MEMBER", self.edition["id"]))
        with self.assertRaises(cases.CaseConflict):
            self.create_collection()
        self.assertFalse(CollectionRevision.objects.exists())

    def test_independent_review_approval_and_lease_bounds(self):
        row = self.create_collection()
        with self.assertRaises(cases.CaseConflict):
            self.collection_action(row, "REVIEW", subject_id="editor")
        row = self.collection_action(row, "REVIEW")
        for subject in ("editor", "other"):
            with self.assertRaises(cases.CaseConflict):
                self.collection_action(row, "APPROVE", subject_id=subject)
        row = self.collection_action(row, "APPROVE")
        with self.assertRaises(cases.CaseConflict):
            self.collection_action(row, "RELEASE", minutes=90)
        self.assertEqual(CollectionAction.objects.count(), 2)

    def test_reorder_and_remove_create_new_drafts_preserving_old_exact_pins(self):
        _, second = self.second_publication()
        first = self.release_collection(
            self.create_collection(members=[self.member(), self.member(second)])
        )
        old = CollectionRevision.objects.get(pk=first["id"]).payload
        reordered = services.reorder(
            **self.common,
            revision_id=first["id"],
            index=1,
            direction="UP",
            expected_version=1,
            expected_revision=4,
            expected_evidence_version=2,
            request_key=uuid.uuid4(),
        )
        self.assertEqual(reordered["stage"], "DRAFT")
        self.assertEqual(CollectionRevision.objects.get(pk=first["id"]).payload, old)
        self.assertEqual(
            CollectionRevision.objects.get(pk=reordered["id"]).payload["members"],
            old["members"][::-1],
        )
        self.assertEqual(self.client.get(self.collection_url(first)).status_code, 404)
        removed = self.create_collection(
            series_id=first["series_id"], expected_version=2, members=[self.member(second)]
        )
        self.assertEqual(removed["number"], 3)
        self.assertEqual(
            len(CollectionRevision.objects.get(pk=removed["id"]).payload["members"]), 1
        )

    def test_replay_and_stale_case_or_content_version_do_not_duplicate_rows(self):
        key = uuid.uuid4()
        row = self.create_collection(request_key=key)
        self.assertEqual(self.create_collection(request_key=key)["id"], row["id"])
        for changes in (
            {"request_key": key, "title": "changed"},
            {"expected_revision": 3},
            {"series_id": row["series_id"], "expected_version": 0},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.create_collection(**changes)
        reviewed = self.collection_action(row, "REVIEW", request_key=key)
        replay = self.collection_action(row, "REVIEW", request_key=key)
        self.assertEqual(reviewed["action_count"], replay["action_count"])
        self.assertEqual(CollectionAction.objects.count(), 1)

    def test_withdrawn_member_hides_whole_collection_without_title_or_count(self):
        row = self.release_collection(self.create_collection(title="اسم مجموعة لا يظهر بعد السحب"))
        self.withdraw()
        response = self.client.get("/library-preview/collections/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "اسم مجموعة لا يظهر بعد السحب")
        self.assertNotContains(response, "عنوان تجريبي")
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        self.assertEqual(CollectionAction.objects.count(), 3)
        row = self.collection_action(row, "WITHDRAW")
        self.assertEqual(row["stage"], "WITHDRAWN")

    def test_source_withdrawal_during_render_discards_complete_response(self):
        row = self.release_collection(self.create_collection())
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.withdraw()
            return response

        with patch.object(views, "render", side_effect=withdraw):
            response = self.client.get(self.collection_url(row))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "مجموعة بشرية", status_code=404)

    def test_collection_withdrawal_during_render_discards_all_cards(self):
        row = self.release_collection(self.create_collection())
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.collection_action(row, "WITHDRAW")
            return response

        with patch.object(views, "render", side_effect=withdraw):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)

    def test_final_callback_policy_and_identity_revocation_are_detected(self):
        row = self.release_collection(self.create_collection())
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.collections_authority.denied.add(("READ_MEMBER", self.edition["id"]))
            return response

        with patch.object(views, "render", side_effect=revoke):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        self.collections_authority.denied.clear()
        self.directory.identities["publisher"] = replace(
            self.directory.identities["publisher"], active=False
        )
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)

    def test_exact_revoke_does_not_fall_back_to_prior_lease(self):
        row = self.release_collection(self.create_collection())
        row = self.collection_action(row, "RELEASE")
        row = self.collection_action(row, "REVOKE")
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        self.assertEqual(CollectionAction.objects.filter(action="RELEASE").count(), 2)

    def test_late_source_callback_revokes_distinct_collection_release_actor(self):
        material = self.library_record()
        self.directory.identities["curator"] = replace(
            self.directory.identities["publisher"], subject_id="curator"
        )
        self.collections_authority.subjects.add("curator")
        row = self.create_collection(
            members=[f"LIBRARY|{material['version_id']}|{material['digest']}"]
        )
        row = self.collection_action(self.collection_action(row, "REVIEW"), "APPROVE")
        row = self.collection_action(row, "RELEASE", subject_id="curator")
        original = views.render
        called = False

        def render(*args, **kwargs):
            response = original(*args, **kwargs)

            def source_callback(_):
                nonlocal called
                if not called:
                    called = True
                    self.directory.identities["curator"] = replace(
                        self.directory.identities["curator"], active=False
                    )

            self.library_authority.hook = source_callback
            return response

        with patch.object(views, "render", side_effect=render):
            response = self.client.get(self.collection_url(row))
        self.assertTrue(called)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "مجموعة بشرية", status_code=404)

    def test_missing_atomic_directory_snapshot_denies_new_collection(self):
        self.directory.projection_epoch = None
        with self.assertRaises(cases.CaseConflict):
            self.create_collection()
        self.assertEqual(CollectionRevision.objects.count(), 0)

    def test_released_parent_and_cross_case_sources_make_topic_hierarchy(self):
        _, second = self.second_publication()
        parent = self.release_collection(
            self.create_collection(kind="TOPIC", title="أصل موضوعي", members=[])
        )
        child = self.release_collection(
            self.create_collection(
                kind="TOPIC",
                title="فرع موضوعي",
                parent_id=parent["id"],
                members=[self.member(), self.member(second)],
            )
        )
        self.assertContains(self.client.get(self.collection_url(parent)), "فرع موضوعي")
        self.assertContains(self.client.get(self.collection_url(child)), "أصل موضوعي")
        with self.assertRaises(cases.CaseConflict):
            self.create_collection(
                kind="TOPIC",
                series_id=parent["series_id"],
                expected_version=1,
                parent_id=child["id"],
            )
        self.collection_action(parent, "WITHDRAW")
        self.assertEqual(self.client.get(self.collection_url(child)).status_code, 404)

    def test_library_metadata_member_has_exact_version_without_private_bytes(self):
        material = self.library_record(raw=b"PRIVATE original synthetic library bytes")
        row = self.release_collection(
            self.create_collection(
                members=[self.member(), f"LIBRARY|{material['version_id']}|{material['digest']}"]
            )
        )
        response = self.client.get(self.collection_url(row))
        self.assertContains(response, "مرجع وصفي اصطناعي")
        self.assertNotContains(response, "PRIVATE original")
        self.assertNotContains(response, material["item_id"])
        library.decide(
            **{**self.common, "subject_id": "publisher"},
            version_id=material["version_id"],
            action="REVOKE",
            expected_actions=material["action_count"],
            expected_revision=4,
            expected_evidence_version=2,
            request_key=uuid.uuid4(),
            confirmed=True,
            note="سحب حقوق اصطناعي",
        )
        self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)

    def test_cross_reader_final_callback_library_withdrawal_cannot_leak_old_card(self):
        material = self.library_record()
        row = self.release_collection(
            self.create_collection(
                members=[f"LIBRARY|{material['version_id']}|{material['digest']}"]
            )
        )
        original = views.render
        fired = False

        def render(*args, **kwargs):
            nonlocal fired
            response = original(*args, **kwargs)

            def callback(values):
                nonlocal fired
                if not fired:
                    fired = True
                    library.decide(
                        **{**self.common, "subject_id": "publisher"},
                        version_id=material["version_id"],
                        action="REVOKE",
                        expected_actions=material["action_count"],
                        expected_revision=4,
                        expected_evidence_version=2,
                        request_key=uuid.uuid4(),
                        confirmed=True,
                        note="سحب بعد بناء الصفحة",
                    )

            self.collections_authority.hook = callback
            return response

        with patch.object(views, "render", side_effect=render):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        self.assertTrue(fired)

    def test_library_actual_bytes_are_rechecked_after_later_reader_callbacks(self):
        material = self.library_record(raw=b"original synthetic bytes")
        row = self.release_collection(
            self.create_collection(
                members=[f"LIBRARY|{material['version_id']}|{material['digest']}"]
            )
        )
        original = views.render

        def render(*args, **kwargs):
            response = original(*args, **kwargs)
            # A failed actual-byte read after render must not be hidden by valid
            # immutable metadata; this is the outer source-pin path.
            self.addCleanup(patcher.stop)
            patcher.start()
            return response

        patcher = patch.object(
            library, "_raw", side_effect=cases.CaseConflict("changed_source_bytes")
        )
        with patch.object(views, "render", side_effect=render):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)

    def test_database_history_and_typed_source_pins_are_enforced(self):
        row = self.release_collection(self.create_collection())
        for model, values in (
            (CollectionSeries, {"kind": "HOME"}),
            (CollectionRevision, {"payload": {}}),
            (CollectionAction, {"note": "tamper"}),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().update(**values)
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().delete()
        stored = CollectionRevision.objects.get(pk=row["id"])
        forged = CollectionRevision(
            series=stored.series,
            number=2,
            case_revision=4,
            evidence_version=2,
            payload={
                **stored.payload,
                "members": [{**stored.payload["members"][0], "sha256": "f" * 64}],
            },
            request_key=uuid.uuid4(),
            provider_id=stored.provider_id,
            subject_id=stored.subject_id,
            auth_epoch=stored.auth_epoch,
        )
        forged.sha256 = services.fingerprint(forged)
        with self.assertRaises(IntegrityError), transaction.atomic():
            forged.save()

    def test_concurrent_revision_has_one_winner(self):
        row = self.create_collection()

        def write(number):
            connections.close_all()
            try:
                return self.create_collection(
                    series_id=row["series_id"], expected_version=1, title=f"تعديل {number}"
                )["number"]
            except cases.CaseConflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, (1, 2)))
        self.assertCountEqual(outcomes, [2, "conflict"])
        self.assertEqual(CollectionRevision.objects.count(), 2)

    def test_native_csrf_edit_review_release_and_read_history(self):
        clients = {
            subject: self.staff_client(subject) for subject in ("editor", "other", "publisher")
        }
        client = clients["editor"]
        response = post(
            client,
            "/casework/staff/",
            {"action": "pc_open", "case_ref": self.receipt["public_ref"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pc-edit-form"')
        values = dict(
            action="pc_save",
            case_ref=self.receipt["public_ref"],
            revision="4",
            evidence_version="2",
            request_key=str(uuid.uuid4()),
            series_id="",
            expected_version="0",
            kind="HOME",
            title="اختيارات مراجعة عبر النماذج",
            introduction="مقدمة بشرية",
            parent_id="",
            featured="yes",
            members=[self.member()],
        )
        response = post(client, "/casework/staff/", values)
        self.assertEqual(response.status_code, 200, response.content)
        row = CollectionRevision.objects.get()
        for sequence, action in enumerate(("REVIEW", "APPROVE", "RELEASE")):
            subject = "other" if action == "REVIEW" else "publisher"
            response = post(
                clients[subject],
                "/casework/staff/",
                dict(
                    action="pc_act",
                    case_ref=self.receipt["public_ref"],
                    revision="4",
                    evidence_version="2",
                    request_key=str(uuid.uuid4()),
                    revision_id=str(row.pk),
                    expected_actions=str(sequence),
                    command=action,
                    note="مراجعة مستقلة",
                    minutes="15" if action == "RELEASE" else "0",
                    related_id="",
                    confirmed="yes",
                ),
            )
            self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(
            self.client.get("/library-preview/collections/"), "اختيارات مراجعة عبر النماذج"
        )
        response = client.post(
            "/casework/staff/", {"action": "pc_open", "case_ref": self.receipt["public_ref"]}
        )
        self.assertEqual(response.status_code, 403)

    def test_native_render_withdrawal_invalidates_history_and_release_controls(self):
        row = self.release_collection(self.create_collection())
        client = self.staff_client()
        original = editor.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.collection_action(row, "WITHDRAW")
            return response

        with patch.object(editor, "render", side_effect=withdraw):
            response = post(
                client,
                "/casework/staff/",
                {"action": "pc_open", "case_ref": self.receipt["public_ref"]},
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'class="pc-release"', status_code=409)

    def test_native_save_and_response_roll_back_together_when_render_loses_rights(self):
        client = self.staff_client()
        original = editor.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            record = CollectionRevision.objects.get()
            self.collections_authority.denied.add(("READ", str(record.pk)))
            return response

        with patch.object(editor, "render", side_effect=revoke):
            response = post(
                client,
                "/casework/staff/",
                dict(
                    action="pc_save",
                    case_ref=self.receipt["public_ref"],
                    revision="4",
                    evidence_version="2",
                    request_key=str(uuid.uuid4()),
                    series_id="",
                    expected_version="0",
                    kind="COLLECTION",
                    title="عنوان لا يبقى بعد رفض الاستجابة",
                    introduction="مقدمة بشرية",
                    parent_id="",
                    members=[self.member()],
                ),
            )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(CollectionSeries.objects.exists())
        self.assertFalse(CollectionRevision.objects.exists())
        self.assertFalse(CollectionAction.objects.exists())

    def test_query_topic_filter_empty_state_escaping_and_remote_denial(self):
        row = self.release_collection(
            self.create_collection(kind="TOPIC", title="<script>مرجع تجريبي</script>")
        )
        response = self.client.get(
            "/library-preview/collections/",
            {"q": "مرجع", "kind": "TOPIC", "topic": row["public_id"]},
        )
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertContains(
            self.client.get("/library-preview/collections/", {"q": "كلمة غير موجودة"}),
            "لا توجد صفحات منتقاة",
        )
        self.assertEqual(
            self.client.get("/library-preview/collections/", {"unknown": "value"}).status_code, 400
        )
        self.assertEqual(
            self.client.get(self.collection_url(row), REMOTE_ADDR="203.0.113.7").status_code, 403
        )
        self.assertEqual(
            self.client.get(
                self.collection_url(row), HTTP_X_FORWARDED_HOST="example.com"
            ).status_code,
            403,
        )

    def test_expiry_and_default_flags_cannot_publish(self):
        row = self.release_collection(self.create_collection())
        lease = CollectionAction.objects.get(pk=row["lease_id"])
        with patch.object(timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        with override_settings(FATWA_PUBLIC_COLLECTIONS_ENABLED=False):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
        with override_settings(FATWA_PUBLIC_COLLECTIONS_AUTHORITY=None):
            self.assertEqual(self.client.get(self.collection_url(row)).status_code, 404)
