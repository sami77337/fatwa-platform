"""External lexical challenges beyond the original SEC13-01 reproductions."""

import os
from hashlib import sha256

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from apps.platform_recovery import service

ARRAY = "(ARRAY['A'::character varying, 'B'::character varying])::text[]"
ELEMENTS = "ARRAY[('A'::character varying)::text, ('B'::character varying)::text]"
OLD_DATA = "(ARRAY['::character varying])::text[]"
NEW_DATA = "ARRAY[('::character varying)::text]"


def quoted(value):
    return "'" + value.replace("'", "''") + "'"


class ExternalLexerRepairTests(SimpleTestCase):
    def test_opaque_neighbors_stay_exact_while_real_array_expression_normalizes(self):
        encoders = (
            quoted,
            lambda value: "E'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'",
            lambda value: "U&" + quoted(value.replace("\\", "\\\\")),
            lambda value: "$review_body$" + value + "$review_body$",
        )
        prefix = "literal \\ quote ' -- /* ;\r\n\\restrict inside_literal\r\n"
        for encode in encoders:
            a, b = encode(prefix + OLD_DATA), encode(prefix + NEW_DATA)
            index = "CREATE UNIQUE INDEX example ON t(x) WHERE x <> {} AND x = ANY ({});\r\n"
            with self.subTest(encoding=encode.__name__):
                before = service.canonical_schema(index.format(a, ARRAY))
                equivalent = service.canonical_schema(index.format(a, ELEMENTS))
                changed = service.canonical_schema(index.format(b, ARRAY))
                self.assertEqual(before, equivalent)
                self.assertIn(a.encode(), before)
                self.assertTrue(before.endswith(b";\r\n"))
                self.assertNotEqual(before, changed)

    def test_comments_inside_candidate_disable_fold_and_unsupported_context_stays_exact(self):
        for comment in ("/* /* nested */ retained */", "-- retained\r\n", "-- retained\r"):
            candidate = ARRAY.replace("'A'", comment + "'A'", 1)
            source = "CREATE INDEX example ON t(x) WHERE x = ANY (" + candidate + ");"
            with self.subTest(comment=comment):
                self.assertEqual(service.canonical_schema(source), source.encode())
        for statement in (
            "SELECT " + ARRAY + ";",
            "CREATE VIEW v AS SELECT " + ARRAY + ";",
            'CREATE INDEX "WHERE ' + OLD_DATA.replace('"', '""') + '" ON t(x);',
            'CREATE TABLE t ("CONSTRAINT x CHECK (' + OLD_DATA + ')" text);',
        ):
            with self.subTest(statement=statement):
                self.assertEqual(service.canonical_schema(statement), statement.encode())

    def test_lexical_denial_has_fixed_code_and_never_echoes_opaque_input(self):
        for suffix in ("'", '"', "E'\\", "U&'", 'U&"', "$private$", "/* /* closed */"):
            raw = "SELECT " + suffix + "PRIVATE_SENTINEL"
            with self.subTest(suffix=suffix):
                with self.assertRaises(service.RecoveryError) as caught:
                    service.canonical_schema(raw)
                self.assertEqual(str(caught.exception), "schema_lexical_unsupported")


class ExternalActualDumpRepairTests(TransactionTestCase):
    def test_real_check_values_with_nonce_comments_escapes_and_crlf_remain_distinct(self):
        tools = service.PostgresTools(os.environ["V12_PG_BIN"])
        database = connection.settings_dict["NAME"]
        prefix = "literal \\ quote ' -- /* $tag$ ;\r\n\\restrict actual_data\r\n"
        values = (prefix + OLD_DATA, prefix + NEW_DATA, (prefix + OLD_DATA).replace("\r\n", "\n"))
        fingerprints, raw_predicates = [], []
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE v13_external_quoted_check (marker text)")
        try:
            for value in values:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER TABLE v13_external_quoted_check DROP CONSTRAINT IF EXISTS exact_value"
                    )
                    cursor.execute(
                        "ALTER TABLE v13_external_quoted_check ADD CONSTRAINT exact_value CHECK (marker <> %s)",
                        [value],
                    )
                    cursor.execute(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'v13_external_quoted_check'::regclass AND conname = 'exact_value'"
                    )
                    raw_predicates.append(cursor.fetchone()[0])
                raw = tools.run(
                    "pg_dump", database, "--schema-only", "--table=public.v13_external_quoted_check"
                ).decode()
                normalized = service.canonical_schema(raw)
                self.assertIn(quoted(value).encode(), normalized)
                fingerprints.append(sha256(normalized).hexdigest())
            self.assertEqual(len(set(raw_predicates)), 3)
            self.assertEqual(len(set(fingerprints)), 3)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE v13_external_quoted_check")
