"""V13 PostgreSQL partial-index deparser regression; schema checks stay exact."""

import json
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.platform_recovery import service
from tests.casework import test_v11_maintenance as existing

LITERALS = "(ARRAY['APPROVE'::character varying, 'REJECT'::character varying])::text[]"
DISTRIBUTED = "ARRAY[('APPROVE'::character varying)::text, ('REJECT'::character varying)::text]"
INDEX = (
    "CREATE UNIQUE INDEX classification_one_decision ON public.classification_review_classificationaction "
    "USING btree (revision_id) WHERE ((action)::text = ANY (" + LITERALS + "));"
)


class SchemaCanonicalTests(SimpleTestCase):
    def test_literal_cast_equivalence_preserves_exact_partial_index_and_check(self):
        before = "\\restrict random1\n" + INDEX + "\n\\unrestrict random1"
        after = (
            "\\restrict random2\n" + INDEX.replace(LITERALS, DISTRIBUTED) + "\n\\unrestrict random2"
        )
        self.assertEqual(service.canonical_schema(before), service.canonical_schema(after))
        check = "    CONSTRAINT decision CHECK ((action)::text = ANY (" + LITERALS + "))"
        self.assertEqual(
            service.canonical_schema(check),
            service.canonical_schema(check.replace(LITERALS, DISTRIBUTED)),
        )

    def test_changed_index_name_uniqueness_values_predicate_or_column_remain_different(self):
        for changed in (
            INDEX.replace("classification_one_decision", "different_name"),
            INDEX.replace("CREATE UNIQUE INDEX", "CREATE INDEX"),
            INDEX.replace("REJECT", "WITHDRAW"),
            INDEX.replace("revision_id", "different_column"),
            INDEX.replace(" = ANY", " <> ALL"),
            INDEX.replace("WHERE", "WHERE true OR"),
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    service.canonical_schema(INDEX), service.canonical_schema(changed)
                )

    def test_function_source_and_nonliteral_arrays_are_never_canonicalized(self):
        for tag in ("$$", "$_$", "$function$"):
            body = (
                "CREATE FUNCTION public.synthetic() RETURNS text\n    LANGUAGE sql\n    AS "
                + tag
                + "\n"
                + INDEX
                + "\n"
                + tag
                + ";"
            )
            self.assertEqual(service.canonical_schema(body), body.encode())
            self.assertNotEqual(
                service.canonical_schema(body),
                service.canonical_schema(body.replace(LITERALS, DISTRIBUTED)),
            )
        nonliteral = INDEX.replace(
            "'REJECT'::character varying", "some_function()::character varying"
        )
        self.assertEqual(service.canonical_schema(nonliteral), nonliteral.encode())


@override_settings(
    FATWA_RECOVERY_MAINTENANCE_REQUIRED=False,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
)
class CurrentSchemaRestoreTests(TransactionTestCase):
    # Reuse the real encrypted/FROZEN fixture without inheriting its unrelated tests.
    setUp = existing.MaintenanceIntegrationTests.setUp
    freeze = existing.MaintenanceIntegrationTests.freeze
    capture = existing.MaintenanceIntegrationTests.capture

    def test_encrypted_roundtrip_preserves_new_tables_guards_and_partial_index(self):
        observed = []
        schema = service.PostgresTools.schema

        def checked(tools, database, snapshot=None):
            result = schema(tools, database, snapshot)
            observed.append(result)
            return result

        with patch.object(service.PostgresTools, "schema", checked):
            existing.MaintenanceIntegrationTests.test_encrypted_restore_writes_only_proven_new_target_while_source_frozen(
                self
            )
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[0], observed[1])
        for statement in (
            b"CREATE TABLE public.classification_review_classificationaction",
            b"CREATE TABLE public.classification_review_classificationrevision",
            b"CREATE TABLE public.timed_citations_timedcitation",
            b"CREATE TABLE public.timed_citations_timedcitationaction",
            b"CREATE FUNCTION public.classification_review_guard()",
            b"CREATE FUNCTION public.timed_citations_guard()",
            b"CREATE FUNCTION public.timed_citations_action_guard()",
            b"CREATE UNIQUE INDEX classification_one_decision",
            b"CONSTRAINT classification_action_once",
            b"CONSTRAINT tc_action_once",
            b"CREATE TRIGGER timed_citations_guard",
            b"CREATE TRIGGER classification_review_revision_guard",
        ):
            self.assertIn(statement, observed[0])

    def test_changed_partial_index_on_real_restored_target_is_quarantined(self):
        changed = []

        def alter(stage):
            if stage != "schema_restored":
                return
            records = sorted(
                self.root.glob("restore-*/journal.json"), key=lambda path: path.stat().st_mtime_ns
            )
            state = json.loads(records[-1].read_text())
            with service.connect(state["database"]) as db:
                db.execute("DROP INDEX public.classification_one_decision")
                db.execute(INDEX.replace("CREATE UNIQUE INDEX", "CREATE INDEX"))
            changed.append(state["database"])

        with patch.object(service, "checkpoint", side_effect=alter):
            with self.assertRaisesRegex(service.RecoveryError, "restored_schema_mismatch"):
                existing.MaintenanceIntegrationTests.test_encrypted_restore_writes_only_proven_new_target_while_source_frozen(
                    self
                )
        self.assertEqual(len(changed), 1)
        with service.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM pg_database WHERE datname=%s", [changed[0]]
                ).fetchone()[0],
                0,
            )
