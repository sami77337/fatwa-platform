"""Real PostgreSQL retrieval, source isolation, concurrent rebuild and late denial."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

from django.conf import settings
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseSource
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.research_workspace.rights import ResearchRights

from . import services, sources
from .models import SearchDocument, SearchGeneration
from .test_support import FEATURES, FixtureAuthority, SearchFixture
from .text import normalize, text_digest


@override_settings(**FEATURES)
class CanonicalSearchTests(SearchFixture, TransactionTestCase):
    def test_real_fts_matches_arabic_words_preserves_original_and_literal_distinction(self):
        self.answer()
        before = (
            CaseSource.objects.get().original_question,
            AnswerRevision.objects.get().text,
            CaseEvent.objects.count(),
        )
        self.build()
        with CaptureQueriesContext(connection) as captured:
            found = self.search("المعاملات المالية", mode="FTS")
        self.assertEqual({row["kind"] for row in found["results"]}, {"QUESTION", "ANSWER"})
        sql = "\n".join(row["sql"] for row in captured)
        self.assertIn("@@", sql)
        self.assertIn("plainto_tsquery", sql)
        self.assertIn("ts_rank_cd", sql)
        self.assertEqual(self.search("المعاملات المالية", mode="LITERAL")["results"], [])
        exact = self.search("المُعاملاتِ", mode="LITERAL")
        self.assertEqual(len(exact["results"]), 1)
        row = exact["results"][0]
        opened = services.open_source(
            **self.common, generation_id=row["generation_id"], document_id=row["document_id"]
        )
        self.assertEqual(opened["text"], self.question)
        self.assertEqual(
            before,
            (
                CaseSource.objects.get().original_question,
                AnswerRevision.objects.get().text,
                CaseEvent.objects.count(),
            ),
        )

    def test_fuzzy_is_explicit_sql_word_similarity_and_threshold_is_restored(self):
        self.build()
        self.assertEqual(self.search("المعاملاتت", mode="FTS")["results"], [])
        with connection.cursor() as cursor:
            cursor.execute("SET pg_trgm.word_similarity_threshold = '0.79'")
        with CaptureQueriesContext(connection) as captured:
            result = self.search("المعاملاتت", mode="FUZZY")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["mode"], "FUZZY")
        self.assertEqual(self.search("المعاملاتت", mode="LITERAL")["results"], [])
        sql = "\n".join(row["sql"] for row in captured)
        self.assertIn("word_similarity", sql)
        self.assertIn("%>", sql)
        with connection.cursor() as cursor:
            cursor.execute("SHOW pg_trgm.word_similarity_threshold")
            self.assertEqual(cursor.fetchone()[0], "0.79")

    def test_real_gin_indexes_and_vector_are_usable_by_postgres(self):
        self.build()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexname,indexdef FROM pg_indexes WHERE tablename='canonical_search_searchdocument'"
            )
            indexes = dict(cursor.fetchall())
            self.assertIn("USING gin (vector)", indexes["cs_document_fts_gin"])
            self.assertIn("gin_trgm_ops", indexes["cs_document_trgm_gin"])
            cursor.execute(
                "SELECT vector = to_tsvector('simple', normalized_text), length(vector) FROM canonical_search_searchdocument"
            )
            matches, count = cursor.fetchone()
            self.assertTrue(matches)
            self.assertGreater(count, 0)
        # A tiny test table may correctly choose a sequential scan. This EXPLAIN
        # explicitly tests index eligibility, not an invented latency guarantee.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan=off")
            cursor.execute(
                "EXPLAIN SELECT id FROM canonical_search_searchdocument WHERE vector @@ plainto_tsquery('simple', %s)",
                ["المعاملات"],
            )
            self.assertIn("cs_document_fts_gin", "\n".join(row[0] for row in cursor.fetchall()))
            cursor.execute(
                "EXPLAIN SELECT id FROM canonical_search_searchdocument WHERE normalized_text %%> %s",
                ["المعاملاتت"],
            )
            self.assertIn("cs_document_trgm_gin", "\n".join(row[0] for row in cursor.fetchall()))

    def test_fuzzy_reader_on_fresh_backend_loads_extension_without_changing_session_default(self):
        self.build()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            builder_pid = cursor.fetchone()[0]
        # A restored database has the extension and GIN index, but each reader
        # backend must load the extension library independently of the builder.
        connection.close()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_backend_pid(), current_setting('pg_trgm.word_similarity_threshold', true)"
            )
            reader_pid, missing = cursor.fetchone()
            self.assertNotEqual(builder_pid, reader_pid)
            self.assertIsNone(missing)
            cursor.execute("SELECT count(*) FROM pg_extension WHERE extname='pg_trgm'")
            self.assertEqual(cursor.fetchone()[0], 1)
        result = self.search("المعاملاتت", mode="FUZZY")
        self.assertEqual(result["total"], 1)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setting, reset_val FROM pg_settings WHERE name='pg_trgm.word_similarity_threshold'"
            )
            setting, initial = cursor.fetchone()
            self.assertEqual(setting, initial)
            self.assertNotEqual(setting, "0.35")

    def test_rebuild_is_idempotent_and_stale_case_version_requires_explicit_new_generation(self):
        first = self.build()
        self.assertFalse(self.build()["created"])
        self.assertEqual(SearchGeneration.objects.count(), 1)
        cases.add_followup(
            token=self.receipt["token"],
            text="تعقيب اصطناعي جديد عن المصارف",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        stale = self.search("المعاملات", mode="FTS")
        self.assertEqual(stale["results"], [])
        self.assertEqual(stale["indexes"][0]["state"], "STALE")
        with self.assertRaises(cases.CaseConflict):
            services.rebuild(
                **self.common,
                expected_revision=1,
                expected_evidence_version=1,
                expected_generation=1,
                request_key=uuid.uuid4(),
            )
        second = self.build()
        self.assertEqual(second["number"], 2)
        self.assertNotEqual(first["generation_id"], second["generation_id"])
        self.assertEqual(self.search("المصارف")["results"][0]["kind"], "FOLLOWUP")

    def test_old_result_is_rejected_after_answer_replacement_and_followup(self):
        self.answer("جواب اصطناعي عن المعاملات")
        self.build()
        old = self.search("المعاملات", kind="ANSWER")["results"][0]
        self.answer("مسودة مختلفة عن الإيداع")
        with self.assertRaises(cases.CaseConflict):
            services.open_source(
                **self.common, generation_id=old["generation_id"], document_id=old["document_id"]
            )
        self.build()
        self.assertEqual(self.search("المعاملات", kind="ANSWER")["results"], [])
        case = Case.objects.get(pk=self.common["case_id"])
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع أحدث",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        self.build()
        self.assertEqual(self.search("الإيداع", kind="ANSWER")["results"], [])

    def test_old_request_replay_does_not_claim_superseded_generation_is_current(self):
        self.transcript()
        first = self.build()
        original = SearchGeneration.objects.get(pk=first["generation_id"])
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        self.build()
        self.rights.denied.clear()
        with self.assertRaises(cases.CaseConflict):
            services.rebuild(
                **self.common,
                expected_revision=original.case_revision,
                expected_evidence_version=original.evidence_version,
                expected_generation=0,
                request_key=original.request_key,
            )
        self.assertEqual(SearchGeneration.objects.count(), 2)
        self.assertEqual(self.search("لاختبار حفظ النص")["indexes"][0]["state"], "STALE")
        self.assertEqual(self.build()["number"], 3)
        self.assertEqual(self.search("لاختبار حفظ النص")["total"], 1)

    def test_transcript_search_uses_actual_segment_pins_and_never_evidence_permission_bypass(self):
        link, entry = self.transcript()
        self.build()
        result = self.search("لاختبار حفظ النص", kind="TRANSCRIPT")
        self.assertEqual(len(result["results"]), 1)
        row = result["results"][0]
        self.assertEqual(row["pin"]["source_id"], link["link_id"])
        self.assertEqual(row["pin"]["segment_sha256"], entry.question.sha256)
        self.assertEqual(row["pin"]["start_ms"], entry.question.start_ms)
        self.assertFalse(SearchDocument.objects.filter(kind="FOLLOWUP").exists())
        self.rights.denied.add(("TRANSCRIPT", "SEARCH_TEXT"))
        denied = self.search("لاختبار حفظ النص")
        self.assertEqual(denied["results"], [])
        self.assertEqual(denied["total"], 0)
        with self.assertRaises(cases.CaseConflict):
            services.open_source(
                **self.common, generation_id=row["generation_id"], document_id=row["document_id"]
            )
        self.rights.denied.clear()
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        self.assertEqual(self.search("لاختبار حفظ النص")["results"], [])
        self.rights.denied.clear()
        self.knowledge.allow_open = False
        self.assertEqual(self.search("لاختبار حفظ النص")["results"], [])

    def test_unusable_optional_transcript_policy_cannot_block_or_leak_question_search(self):
        self.transcript()

        class Unversioned(ResearchRights):
            def permits(self, **values):
                raise AssertionError("unversioned policy must not be queried")

        with override_settings(FATWA_RESEARCH_WORKSPACE_RIGHTS=Unversioned()):
            self.build()
            self.assertEqual(len(self.search("المعاملات")["results"]), 1)
            self.assertEqual(self.search("لاختبار حفظ النص")["results"], [])
        self.assertEqual(self.search("لاختبار حفظ النص")["indexes"][0]["state"], "STALE")
        self.build()
        self.assertEqual(len(self.search("لاختبار حفظ النص")["results"]), 1)

    def test_scoped_search_omits_unassigned_private_case_counts_and_rechecks_inter_row_scope(self):
        other = self.new_case("سؤال اصطناعي خاص عن المعاملات ورمز خاصثان")
        self.grant(other["public_ref"])
        self.build()
        self.build(case_id=other["case_id"])
        self.assertEqual(self.search("المعاملات", scope="SCOPED")["total"], 2)
        actor = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(
            actor, case_keys=frozenset({self.receipt["public_ref"]})
        )
        self.assertEqual(self.search("خاصثان", scope="SCOPED")["total"], 0)
        self.directory.identities["editor"] = actor
        refs = list(
            Case.objects.filter(public_ref__in=actor.case_keys)
            .order_by("pk")
            .values_list("public_ref", flat=True)
        )

        def narrow(values):
            if values["action"] == "SEARCH" and values["case_ref"] == refs[-1]:
                self.directory.identities["editor"] = replace(
                    actor, case_keys=frozenset({refs[-1]})
                )

        self.authority.hook = narrow
        with self.assertRaises((cases.CaseConflict, ValueError)):
            self.search("المعاملات", scope="SCOPED")

    def test_late_value_equal_authority_replacement_is_denied(self):
        self.build()

        class EqualAuthority(FixtureAuthority):
            def __eq__(self, other):
                return True

        replacement = EqualAuthority(self.receipt["public_ref"])
        count = 0

        def swap(values):
            nonlocal count
            if values["action"] == "SEARCH":
                count += 1
                if count == 2:
                    settings.FATWA_CANONICAL_SEARCH_AUTHORITY = replacement

        self.authority.hook = swap
        with self.assertRaises(cases.CaseConflict):
            self.search("المعاملات")

    def test_last_search_callback_cannot_revoke_transcript_source_read(self):
        self.transcript()
        self.build()
        count = 0

        def revoke(values):
            nonlocal count
            if values["action"] == "SEARCH":
                count += 1
                if count == 2:
                    self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.search("لاختبار حفظ النص")

    def test_late_identity_callback_cannot_revoke_earlier_source_permission(self):
        self.transcript()
        self.build()
        original = self.directory.resolve

        def revoke(subject):
            identity = original(subject)
            if any(row["action"] == "SEARCH" for row in self.authority.calls):
                self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
            return identity

        self.directory.resolve = revoke
        with self.assertRaises(cases.CaseConflict):
            self.search("لاختبار حفظ النص")

    def test_late_rebuild_denial_rolls_back_all_rows_and_preserves_canonical_sources(self):
        before = sources.fingerprint([self.receipt["case_id"]])
        count = 0

        def revoke(values):
            nonlocal count
            if values["action"] == "REBUILD":
                count += 1
                if count == 2:
                    self.authority.denied.add("REBUILD")

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.build()
        self.assertEqual(SearchGeneration.objects.count(), 0)
        self.assertEqual(SearchDocument.objects.count(), 0)
        self.assertEqual(sources.fingerprint([self.receipt["case_id"]]), before)

    def test_concurrent_rebuilds_keep_one_complete_generation(self):
        request_key = uuid.uuid4()

        def run():
            close_old_connections()
            try:
                return services.rebuild(
                    **self.common,
                    expected_revision=1,
                    expected_evidence_version=1,
                    expected_generation=0,
                    request_key=request_key,
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(
            {row["generation_id"] for row in results}, {str(SearchGeneration.objects.get().pk)}
        )
        self.assertEqual(sum(row["created"] for row in results), 1)
        self.assertEqual(SearchDocument.objects.count(), 1)

    def test_sql_immutable_rows_forged_text_and_incomplete_generation_are_rejected(self):
        self.build()
        generation, document = SearchGeneration.objects.get(), SearchDocument.objects.get()
        for operation in (
            lambda: SearchGeneration.objects.filter(pk=generation.pk).update(profile="forged"),
            lambda: SearchDocument.objects.filter(pk=document.pk).update(original_text="forged"),
            lambda: SearchDocument.objects.filter(pk=document.pk).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        with self.assertRaises(IntegrityError), synthetic_queue_atomic():
            clone = SearchGeneration(
                **{
                    field.attname: getattr(generation, field.attname)
                    for field in generation._meta.fields
                    if field.name
                    not in {"id", "number", "request_key", "created_at", "transaction_id"}
                }
            )
            clone.number, clone.request_key = 2, uuid.uuid4()
            services._seal(clone)
            # The real deferred trigger rejects a generation with missing rows.
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS cs_generation_complete IMMEDIATE")
        self.assertEqual(SearchGeneration.objects.count(), 1)

    def test_sql_new_generation_rejects_forged_question_text_and_duplicate_pins(self):
        self.build()
        original = SearchGeneration.objects.get()
        fields = {
            field.attname: getattr(original, field.attname)
            for field in original._meta.fields
            if field.name not in {"id", "number", "request_key", "created_at", "transaction_id"}
        }
        forged = "نص مزور ليس السؤال الأصلي"
        manifest = deepcopy(original.manifest)
        manifest[0]["pin"]["text_sha256"] = text_digest(forged)
        manifest[0]["derived_sha256"] = text_digest(normalize(forged))
        with self.assertRaises(IntegrityError), synthetic_queue_atomic():
            row = services._seal(
                SearchGeneration(
                    **{**fields, "number": 2, "request_key": uuid.uuid4(), "manifest": manifest}
                )
            )
            services._seal(
                SearchDocument(
                    generation=row,
                    ordinal=1,
                    kind="QUESTION",
                    source_id=self.receipt["case_id"],
                    pin=manifest[0]["pin"],
                    original_text=forged,
                    normalized_text=normalize(forged),
                )
            )
        with self.assertRaises(IntegrityError), synthetic_queue_atomic():
            services._seal(
                SearchGeneration(
                    **{
                        **fields,
                        "number": 2,
                        "request_key": uuid.uuid4(),
                        "manifest": original.manifest * 2,
                    }
                )
            )
        self.assertEqual(SearchGeneration.objects.count(), 1)
        self.assertEqual(CaseSource.objects.get().original_question, self.question)

    def test_default_flags_missing_authority_and_provider_replacement_fail_closed(self):
        self.build()
        for name, value in (
            ("FATWA_CANONICAL_SEARCH_ENABLED", False),
            ("FATWA_CANONICAL_SEARCH_AUTHORITY", None),
        ):
            with override_settings(**{name: value}), self.assertRaises(cases.CaseConflict):
                self.search("المعاملات")
        count = 0

        def swap(values):
            nonlocal count
            if values["action"] == "SEARCH":
                count += 1
                if count == 2:
                    self.directory.provider_id = "different-provider"

        self.authority.hook = swap
        with self.assertRaises(cases.CaseConflict):
            self.search("المعاملات")

    def test_query_boundaries_are_not_raw_sql_or_tsquery_and_no_empty_global_search(self):
        self.build()
        for value, mode in (
            ("", "FTS"),
            ("***", "FTS"),
            ("a" * 121, "FTS"),
            ("من", "FUZZY"),
            ("أ\x00ب", "LITERAL"),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.search(value, mode=mode)
        self.assertEqual(self.search("' OR 1=1 --", mode="LITERAL")["results"], [])
        self.assertEqual(self.search("المعاملات | nonexistent", mode="FTS")["results"], [])
