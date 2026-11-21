"""PostgreSQL and native HTTP evidence for private research collections."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch

from django.db import DatabaseError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent
from apps.mufti_review.identity import IdentityUnavailable

from . import collection_views, collections, services, views
from . import test_source_rights as source_rights_tests
from . import tests as research_tests
from .models import ResearchCollection, ResearchCollectionEvent, ResearchItem, SavedResearchSearch
from .rights import Resource
from .tests import SETTINGS, ResearchFixture

FEATURES = {**SETTINGS, "FATWA_RESEARCH_COLLECTIONS_ENABLED": True}


class CollectionFixture(ResearchFixture):
    def pins(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return dict(
            expected_case_revision=case.revision, expected_evidence_version=case.evidence_version
        )

    def create(self, title="مراجع القضية الخاصة"):
        return collections.create_collection(**self.common, **self.pins(), title=title)

    def change(self, collection, action, **kw):
        return collections.change_collection(
            **self.common,
            **self.pins(),
            collection_id=collection["id"],
            expected_revision=collection["collection_revision"],
            action=action,
            **kw,
        )

    def read(self, collection):
        return collections.read_collection(**self.common, collection_id=collection["id"])

    def transcript_resource(self):
        return Resource(**self.search(kind="TRANSCRIPT")["results"][0]["resource"])


@override_settings(**FEATURES)
class CollectionTests(CollectionFixture, TransactionTestCase):
    def test_private_selection_notes_order_and_exact_comparison_do_not_edit_sources(self):
        before = (CaseEvent.objects.count(), AnswerRevision.objects.count(), self.pins())
        collection = self.create()
        first, second = self.source(2), self.transcript_resource()
        collection = self.change(collection, "ADD", resource=first, note="ملاحظة بشرية منفصلة")
        collection = self.change(collection, "ADD", resource=second)
        result = self.read(collection)
        ids = [r["id"] for r in result["items"]]
        opened = collections.open_items(
            **self.common,
            collection_id=collection["id"],
            expected_revision=collection["collection_revision"],
            item_ids=ids,
        )
        self.assertEqual(opened["opened"][0]["opened"]["source"]["source_row_id"], 2)
        self.assertEqual(opened["opened"][1]["opened"]["question"]["text"], self.transcript_text)
        self.assertEqual(opened["opened"][1]["opened"]["question"]["start_ms"], 0)
        self.assertNotIn(self.transcript_text, str(list(ResearchItem.objects.values())))
        collection = self.change(
            collection, "NOTE", item_id=ids[0], note="  رأيي الخاص\nلا يبدل المصدر  "
        )
        collection = self.change(collection, "MOVE", item_id=ids[1], direction="up")
        result = self.read(collection)
        self.assertEqual([r["id"] for r in result["items"]], list(reversed(ids)))
        self.assertEqual(result["items"][1]["note"], "  رأيي الخاص\nلا يبدل المصدر  ")
        collection = self.change(collection, "REMOVE", item_id=ids[1])
        result = self.read(collection)
        self.assertEqual([(r["id"], r["ordinal"]) for r in result["items"]], [(ids[0], 1)])
        self.assertEqual(
            (CaseEvent.objects.count(), AnswerRevision.objects.count(), self.pins()), before
        )
        self.assertEqual(collection["collection_revision"], 6)
        self.assertEqual(
            list(
                ResearchCollectionEvent.objects.order_by("revision").values_list(
                    "action", flat=True
                )
            ),
            ["CREATE", "ADD", "ADD", "NOTE", "MOVE", "REMOVE"],
        )

    def test_approved_fatwa_current_only_and_private_note_revoke(self):
        original_events = CaseEvent.objects.count()
        resource = collections.current_approved_resource(**self.common)
        self.assertEqual(resource.kind, "APPROVED_FATWA")
        self.assertEqual(
            services.open_resource(**self.common, resource=resource)["text"],
            "PRIVATE ANSWER",
        )
        collection = self.change(
            self.create(), "ADD", resource=resource,
            note="PRIVATE APPROVED ANSWER QUOTATION",
        )
        self.assertEqual(CaseEvent.objects.count(), original_events)
        item = self.read(collection)["items"][0]
        self.assertTrue(item["available"])
        self.assertEqual(item["kind"], "APPROVED_FATWA")
        with self.assertRaises(cases.CaseConflict):
            self.change(
                collection, "ADD", resource=replace(resource, sha256="0" * 64)
            )
        self.rights.denied.add(("APPROVED_FATWA", "READ_TEXT"))
        hidden = self.read(collection)["items"][0]
        self.assertEqual(
            hidden, dict(id=item["id"], ordinal=1, available=False)
        )
        with self.assertRaises(cases.CaseConflict):
            collections.open_items(
                **self.common, collection_id=collection["id"],
                expected_revision=collection["collection_revision"],
                item_ids=[item["id"]],
            )
        self.rights.denied.clear()
        pins = self.pins()
        cases.save_answer(
            **self.common,
            expected_revision=pins["expected_case_revision"],
            expected_evidence_version=pins["expected_evidence_version"],
            text="NEW UNSAVED APPROVAL DRAFT",
        )
        self.assertFalse(self.read(collection)["items"][0]["available"])
        with self.assertRaises(cases.CaseConflict):
            collections.current_approved_resource(**self.common)

    def test_saved_search_instructions_replay_with_current_rights_not_cached_results(self):
        collection = self.create()
        filters = dict(
            query="فرع",
            kind="REFERENCE",
            edition_id=self.catalog_id,
            printed_part="",
            printed_page=None,
        )
        collection = self.change(collection, "SAVE_SEARCH", title="فروع الفهرس", filters=filters)
        saved = self.read(collection)["searches"][0]
        loaded = collections.saved_search(
            **self.common,
            collection_id=collection["id"],
            search_id=saved["id"],
            expected_revision=collection["collection_revision"],
        )
        self.assertEqual(loaded, filters)
        self.assertGreater(len(services.search(**self.common, **loaded)["results"]), 0)
        self.rights.denied.add(("REFERENCE", "DISCOVER"))
        self.assertEqual(services.search(**self.common, **loaded)["results"], [])
        self.assertEqual(ResearchItem.objects.count(), 0)
        self.assertEqual(set(SavedResearchSearch.objects.get().filters), collections.FILTER_KEYS)
        collection = self.change(collection, "REMOVE_SEARCH", search_id=saved["id"])
        self.assertEqual(self.read(collection)["searches"], [])

    def test_owner_and_case_scope_are_required_even_with_a_known_collection_id(self):
        collection = self.create()
        other = {**self.common, "subject_id": "publisher"}
        self.assertEqual(collections.list_collections(**other)["collections"], [])
        with self.assertRaisesMessage(cases.CaseConflict, "research_collection_unavailable"):
            collections.read_collection(**other, collection_id=collection["id"])
        with self.assertRaisesMessage(cases.CaseConflict, "research_collection_unavailable"):
            collections.change_collection(
                **other,
                **self.pins(),
                collection_id=collection["id"],
                expected_revision=1,
                action="RENAME",
                title="stolen",
            )
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset()
        )
        with self.assertRaises((cases.CaseConflict, IdentityUnavailable)):
            self.read(collection)
        self.assertEqual(ResearchCollection.objects.get().title, "مراجع القضية الخاصة")

    def test_stale_collection_and_case_conflicts_do_not_overwrite_notes(self):
        collection = self.change(self.create(), "ADD", resource=self.source())
        item_id = self.read(collection)["items"][0]["id"]
        old = collection
        collection = self.change(collection, "NOTE", item_id=item_id, note="current note")
        with self.assertRaisesMessage(cases.CaseConflict, "research_collection_changed"):
            self.change(old, "NOTE", item_id=item_id, note="stale note")
        pins = self.pins()
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع إضافية",
            expected_revision=pins["expected_case_revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            collections.change_collection(
                **self.common,
                **pins,
                collection_id=collection["id"],
                expected_revision=collection["collection_revision"],
                action="NOTE",
                item_id=item_id,
                note="old facts",
            )
        self.assertEqual(ResearchItem.objects.get().note, "current note")
        self.assertEqual(ResearchCollectionEvent.objects.count(), 3)

    def test_revoked_source_hides_source_title_pins_and_quoted_note_but_slot_is_removable(self):
        collection = self.change(
            self.create(), "ADD", resource=self.transcript_resource(), note=self.transcript_text
        )
        item_id = self.read(collection)["items"][0]["id"]
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        self.assertEqual(
            self.read(collection)["items"], [dict(id=item_id, ordinal=1, available=False)]
        )
        with self.assertRaises(cases.CaseConflict):
            collections.open_items(
                **self.common,
                collection_id=collection["id"],
                item_ids=[item_id],
                expected_revision=collection["collection_revision"],
            )
        with self.assertRaises(cases.CaseConflict):
            self.change(collection, "NOTE", item_id=item_id, note="cannot edit quoted source")
        collection = self.change(collection, "REMOVE", item_id=item_id)
        self.assertEqual(self.read(collection)["items"], [])

    def test_mid_projection_revocation_closes_whole_comparison(self):
        reference, transcript = self.source(), self.transcript_resource()
        collection = self.change(
            self.create(), "ADD", resource=reference, note="private source note"
        )
        collection = self.change(collection, "ADD", resource=transcript)
        ids = [r["id"] for r in self.read(collection)["items"]]
        original = services.open_resource

        def revoke(**kw):
            value = original(**kw)
            if kw["resource"].kind == "TRANSCRIPT":
                self.rights.denied.add(("REFERENCE", "READ_METADATA"))
            return value

        with patch.object(services, "open_resource", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                collections.open_items(
                    **self.common,
                    collection_id=collection["id"],
                    item_ids=ids,
                    expected_revision=collection["collection_revision"],
                )

    def test_three_material_comparison_preserves_approved_relationship_and_exact_sources(self):
        relation = self.propose("TRANSCRIPT")
        self.approve(relation)
        linked = Resource(**self.search(kind="KNOWLEDGE")["results"][0]["resource"])
        collection = self.create()
        for resource in (self.source(), self.transcript_resource(), linked):
            collection = self.change(collection, "ADD", resource=resource)
        ids = [r["id"] for r in self.read(collection)["items"]]
        result = collections.open_items(
            **self.common,
            collection_id=collection["id"],
            item_ids=ids,
            expected_revision=collection["collection_revision"],
        )
        self.assertEqual(
            [r["kind"] for r in result["opened"]], ["REFERENCE", "TRANSCRIPT", "KNOWLEDGE"]
        )
        self.assertEqual(result["opened"][2]["opened"]["material"]["text"], self.transcript_text)
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        self.assertEqual(
            [r["available"] for r in self.read(collection)["items"]], [True, False, False]
        )

    def test_identity_epoch_change_during_create_rolls_back_collection_and_audit(self):
        original = collections._record

        def revoke(*args, **kwargs):
            original(*args, **kwargs)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="epoch-2"
            )

        with patch.object(collections, "_record", side_effect=revoke):
            with self.assertRaises((cases.CaseConflict, IdentityUnavailable)):
                self.create()
        self.assertFalse(ResearchCollection.objects.exists())
        self.assertFalse(ResearchCollectionEvent.objects.exists())

    def test_rights_or_identity_withdrawn_during_add_roll_back_item_and_audit(self):
        collection = self.create()
        source = self.source()
        original = collections._record

        def revoke(*args, **kwargs):
            original(*args, **kwargs)
            self.rights.denied.add(("REFERENCE", "READ_METADATA"))

        with patch.object(collections, "_record", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.change(collection, "ADD", resource=source)
        self.assertEqual(ResearchItem.objects.count(), 0)
        self.assertEqual(ResearchCollectionEvent.objects.count(), 1)
        self.assertEqual(ResearchCollection.objects.get().revision, 1)

    def test_wrong_resource_version_duplicate_media_and_invalid_filters_fail_without_writes(self):
        collection = self.create()
        source = self.source()
        for wrong in (
            replace(source, sha256="0" * 64),
            replace(source, source_input_sha256="0" * 64),
            Resource("ATTACHMENT", "not-a-source", "0" * 64),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.change(collection, "ADD", resource=wrong)
        collection = self.change(collection, "ADD", resource=source)
        with self.assertRaisesMessage(cases.CaseConflict, "research_collection_duplicate"):
            self.change(collection, "ADD", resource=source)
        filters = dict(query="x", kind="all", edition_id=None, printed_part="", printed_page=None)
        for wrong in (
            {**filters, "results": ["cached"]},
            {**filters, "edition_id": True},
            {**filters, "query": "x" * 81},
            {**filters, "ranking": "external"},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.change(collection, "SAVE_SEARCH", title="invalid", filters=wrong)
        self.assertEqual(ResearchCollectionEvent.objects.count(), 2)
        self.assertFalse(SavedResearchSearch.objects.exists())

    def test_archive_restore_preserves_original_collection_and_rechecks_access(self):
        collection = self.change(self.create(), "ADD", resource=self.source())
        collection = self.change(collection, "RENAME", title="عنوان جديد")
        collection = self.change(collection, "ARCHIVE")
        self.assertTrue(self.read(collection)["archived"])
        with self.assertRaisesMessage(cases.CaseConflict, "research_collection_archived"):
            self.change(collection, "RENAME", title="no mutation")
        collection = self.change(collection, "RESTORE")
        self.assertFalse(self.read(collection)["archived"])
        self.assertEqual(self.read(collection)["title"], "عنوان جديد")
        self.assertEqual(ResearchItem.objects.count(), 1)

    def test_database_owner_source_and_history_guards_and_state_digest(self):
        collection = self.change(self.create(), "ADD", resource=self.source())
        operations = [
            lambda: ResearchCollection.objects.filter(pk=collection["id"]).update(
                subject_id="other"
            ),
            lambda: ResearchItem.objects.all().update(resource_sha256="f" * 64),
            lambda: ResearchCollectionEvent.objects.all().update(action="RENAME"),
            lambda: ResearchCollectionEvent.objects.all().delete(),
        ]
        for operation in operations:
            with self.assertRaises(DatabaseError), transaction.atomic():
                operation()
        # Even an owner-level direct table edit without a corresponding audited
        # state transition cannot silently become the service's next baseline.
        ResearchItem.objects.all().update(note="unrecorded alteration")
        with self.assertRaisesMessage(cases.CaseConflict, "research_collection_history_invalid"):
            self.read(collection)

    def test_concurrent_note_changes_have_one_winner_and_no_lost_update(self):
        collection = self.change(self.create(), "ADD", resource=self.source())
        item_id = self.read(collection)["items"][0]["id"]
        pins, barrier = self.pins(), Barrier(2)

        def writer(text):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                collections.change_collection(
                    **self.common,
                    **pins,
                    collection_id=collection["id"],
                    expected_revision=collection["collection_revision"],
                    action="NOTE",
                    item_id=item_id,
                    note=text,
                )
                return "saved"
            except cases.CaseConflict as exc:
                return str(exc)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, ["first", "second"]))
        self.assertCountEqual(results, ["saved", "research_collection_changed"])
        self.assertIn(ResearchItem.objects.get().note, {"first", "second"})
        self.assertEqual(ResearchCollectionEvent.objects.count(), 3)

    def test_default_closed_and_collection_comparison_limits(self):
        with override_settings(FATWA_RESEARCH_COLLECTIONS_ENABLED=False):
            with self.assertRaisesMessage(cases.CaseConflict, "research_collections_disabled"):
                self.create()
        collection = self.change(self.create(), "ADD", resource=self.source())
        item_id = self.read(collection)["items"][0]["id"]
        for ids in ([], [item_id, item_id], [item_id] * 4):
            with self.assertRaises(cases.CaseConflict):
                collections.open_items(
                    **self.common,
                    collection_id=collection["id"],
                    expected_revision=collection["collection_revision"],
                    item_ids=ids,
                )
        self.assertEqual(views.COLLECTION_ACTIONS, collection_views.ACTIONS)


@override_settings(**FEATURES)
class CollectionHTTPTests(CollectionFixture, TransactionTestCase):
    login = research_tests.ResearchHTTPTests.login
    send = research_tests.ResearchHTTPTests.send

    def open_http(self, client, page):
        return self.send(client, page, "research_collections")

    def test_native_create_choose_save_note_compare_and_current_search_rerun(self):
        client, page = self.login()
        listing = self.open_http(client, page)
        created = self.send(
            client,
            listing,
            "research_collection_create",
            state=listing.context["result"]["state"],
            title="مجموعة من المتصفح",
        )
        self.assertEqual(created.status_code, 200)
        search = self.send(
            client,
            created,
            "research_search",
            query="فرع",
            kind="REFERENCE",
            edition_id=self.catalog_id,
            printed_part="",
            printed_page="",
        )
        self.assertContains(search, "حفظ في مجموعة خاصة")
        source_state = search.context["result"]["results"][0]["state"]
        chooser = self.send(client, search, "research_collect", source_state=source_state)
        self.assertEqual(chooser.status_code, 200)
        stored = self.send(
            client,
            chooser,
            "research_collection_add",
            source_state=source_state,
            state=chooser.context["result"]["collections"][0]["state"],
            note="ملاحظة <script> محمية",
        )
        self.assertEqual(stored.status_code, 200)
        self.assertContains(stored, "&lt;script&gt;")
        self.assertNotContains(stored, "<script>")
        search = self.send(
            client,
            stored,
            "research_search",
            query="",
            kind="TRANSCRIPT",
            edition_id="",
            printed_part="",
            printed_page="",
        )
        source_state = search.context["result"]["results"][0]["state"]
        chooser = self.send(client, search, "research_collect", source_state=source_state)
        stored = self.send(
            client,
            chooser,
            "research_collection_add",
            source_state=source_state,
            state=chooser.context["result"]["collections"][0]["state"],
            note="",
        )
        rows = stored.context["result"]["items"]
        compared = self.send(
            client,
            stored,
            "research_collection_compare",
            state=stored.context["result"]["state"],
            first_id=rows[0]["id"],
            second_id=rows[1]["id"],
            third_id="",
        )
        self.assertEqual(compared.status_code, 200)
        self.assertContains(compared, self.transcript_text)
        self.assertContains(compared, "مقارنة المواد المختارة")
        self.assertIn("no-store", compared["Cache-Control"])
        chooser = self.send(
            client, compared, "research_save_search", source_state=search.context["back_state"]
        )
        saved = self.send(
            client,
            chooser,
            "research_collection_save_search",
            source_state=search.context["back_state"],
            state=chooser.context["result"]["collections"][0]["state"],
            title="تفريغات القضية",
        )
        self.assertEqual(saved.status_code, 200)
        current_count = ResearchItem.objects.count()
        rerun = self.send(
            client,
            saved,
            "research_collection_run_search",
            state=saved.context["result"]["searches"][0]["state"],
        )
        self.assertEqual(rerun.status_code, 200)
        self.assertEqual(rerun.context["filters"]["kind"], "TRANSCRIPT")
        self.assertEqual(ResearchItem.objects.count(), current_count)

    def test_signed_native_add_current_approved_fatwa_and_revoked_view(self):
        self.create()
        client, page = self.login()
        listing = self.open_http(client, page)
        opened = self.send(
            client, listing, "research_collection_open",
            state=listing.context["result"]["collections"][0]["state"],
        )
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, "collection-add-approved-fatwa")
        saved = self.send(
            client, opened, "research_collection_add_fatwa",
            state=opened.context["result"]["state"],
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        item = saved.context["result"]["items"][0]
        self.assertEqual(item["kind"], "APPROVED_FATWA")
        compared = self.send(
            client, saved, "research_collection_view", state=item["state"]
        )
        self.assertEqual(compared.status_code, 200, compared.content)
        self.assertContains(compared, "PRIVATE ANSWER")
        invalid = self.send(
            client, compared, "research_collection_add_fatwa",
            state=compared.context["result"]["state"],
            source_state="forged-untrusted-source",
        )
        self.assertEqual(invalid.status_code, 400)
        self.rights.denied.add(("APPROVED_FATWA", "READ_TEXT"))
        denied = self.send(
            client, compared, "research_collection_open",
            state=compared.context["result"]["state"],
        )
        self.assertEqual(denied.status_code, 200)
        self.assertNotContains(denied, "PRIVATE ANSWER")
        self.assertContains(denied, "مرجع غير متاح")

    def test_browser_binding_tampering_csrf_extra_fields_and_stale_submission(self):
        collection = self.create()
        client, page = self.login()
        listing = self.open_http(client, page)
        state = listing.context["result"]["collections"][0]["state"]
        second, page2 = self.login()
        self.assertEqual(
            self.send(second, page2, "research_collection_open", state=state).status_code, 400
        )
        self.assertEqual(
            self.send(client, listing, "research_collection_open", state=state + "x").status_code,
            400,
        )
        self.assertEqual(
            self.send(
                client, listing, "research_collection_open", state=state, subject_id="publisher"
            ).status_code,
            400,
        )
        self.assertEqual(
            client.post(
                "/casework/staff/",
                {
                    "action": "research_collection_open",
                    "case_ref": self.receipt["public_ref"],
                    "state": state,
                },
            ).status_code,
            403,
        )
        collection = self.change(collection, "RENAME", title="new title")
        stale = self.send(
            client, listing, "research_collection_rename", state=state, title="stale overwrite"
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(ResearchCollection.objects.get().title, "new title")

    def test_revoked_source_and_its_note_are_absent_from_http_and_guessed_compare(self):
        self.change(
            self.create(),
            "ADD",
            resource=self.transcript_resource(),
            note="PRIVATE_QUOTE_SHOULD_HIDE",
        )
        client, page = self.login()
        listing = self.open_http(client, page)
        state = listing.context["result"]["collections"][0]["state"]
        opened = self.send(client, listing, "research_collection_open", state=state)
        item_state = opened.context["result"]["items"][0]["state"]
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        hidden = self.send(client, opened, "research_collection_open", state=state)
        self.assertEqual(hidden.status_code, 200)
        self.assertNotContains(hidden, self.transcript_text)
        self.assertNotContains(hidden, "PRIVATE_QUOTE_SHOULD_HIDE")
        self.assertContains(hidden, "مرجع غير متاح")
        refused = self.send(client, hidden, "research_collection_view", state=item_state)
        self.assertEqual(refused.status_code, 409)
        self.assertNotIn("PRIVATE_QUOTE_SHOULD_HIDE", refused.content.decode())

    def test_case_change_invalidates_saved_form_without_transferring_note(self):
        self.change(self.create(), "ADD", resource=self.source())
        client, page = self.login()
        listing = self.open_http(client, page)
        opened = self.send(
            client,
            listing,
            "research_collection_open",
            state=listing.context["result"]["collections"][0]["state"],
        )
        item_state = opened.context["result"]["items"][0]["state"]
        cases.add_followup(
            token=self.receipt["token"],
            text="new evidence",
            expected_revision=self.pins()["expected_case_revision"],
            synthetic_fixtures_only=True,
        )
        failed = self.send(
            client, opened, "research_collection_note", state=item_state, note="STALE_PRIVATE_NOTE"
        )
        self.assertEqual(failed.status_code, 409)
        self.assertNotIn("STALE_PRIVATE_NOTE", failed.content.decode())
        self.assertEqual(ResearchItem.objects.get().note, "")


@override_settings(**FEATURES, FATWA_SOURCE_RIGHTS_ENABLED=True)
class CollectionLedgerTests(CollectionFixture, TransactionTestCase):
    grant = source_rights_tests.SourceRightsIntegrationTests.grant

    def setUp(self):
        super().setUp()
        from apps.source_rights import services as ledger
        from apps.source_rights.tests import Authority

        from .source_rights_adapter import SourceRightsAdapter

        self.ledger = ledger
        policy = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
        )
        policy.enable()
        self.addCleanup(policy.disable)

    def test_canonical_approved_fatwa_is_not_external_reference_ledger(self):
        # The signed Casework answer belongs to the same locked case. No
        # source-ledger CITE/EXPORT right may be inferred from this READ.
        with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True):
            resource = collections.current_approved_resource(**self.common)
            self.assertEqual(resource.kind, "APPROVED_FATWA")
            collection = self.change(self.create(), "ADD", resource=resource)
            self.assertTrue(self.read(collection)["items"][0]["available"])
            self.assertEqual(
                services.open_resource(**self.common, resource=resource)["text"],
                "PRIVATE ANSWER",
            )
            with self.assertRaises(cases.CaseConflict):
                self.change(
                    collection, "ADD", resource=replace(resource, sha256="f" * 64)
                )

    def test_actual_current_ledger_revalidation_does_not_inherit_saved_reference_access(self):
        self.grant(row=2)
        granted = self.grant(row=3, uses=("READ",))
        with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True):
            resource = self.source(3)
            collection = self.change(
                self.create(), "ADD", resource=resource, note="private quoted note"
            )
            row = self.read(collection)["items"][0]
            self.assertTrue(row["available"])
            self.ledger.review(
                **{**self.common, "subject_id": "publisher"},
                revision_id=granted["id"],
                action="REVOKE",
                confirmed=True,
                note="human withdrawal",
            )
            self.assertEqual(
                self.read(collection)["items"], [dict(id=row["id"], ordinal=1, available=False)]
            )
            with self.assertRaises(cases.CaseConflict):
                collections.open_items(
                    **self.common,
                    collection_id=collection["id"],
                    item_ids=[row["id"]],
                    expected_revision=collection["collection_revision"],
                )

    def test_cite_grant_is_not_inferred_from_collecting_or_comparing_readable_sources(self):
        self.grant(row=2)
        self.grant(row=3, uses=("READ",))
        with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True):
            resource = self.source(3)
            collection = self.change(self.create(), "ADD", resource=resource)
            item = self.read(collection)["items"][0]
            collections.open_items(
                **self.common,
                collection_id=collection["id"],
                item_ids=[item["id"]],
                expected_revision=collection["collection_revision"],
            )
            before = AnswerRevision.objects.count()
            with self.assertRaises(cases.CaseConflict):
                self.add(resource=resource)
            self.assertEqual(AnswerRevision.objects.count(), before)
