"""Independent SEC13-01 lexer regressions; no product/external-review edits.

Opaque PostgreSQL source must remain exact even when its contents resemble the
one supported literal-array deparser rewrite. No generic SQL pretty printer is
an acceptable recovery fingerprint boundary.
"""

import os
from hashlib import sha256

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from apps.platform_recovery import service

LITERAL = "(ARRAY['ALLOW'::character varying, 'DENY'::character varying])::text[]"
DISTRIBUTED = "ARRAY[('ALLOW'::character varying)::text, ('DENY'::character varying)::text]"
DATA_A = "(ARRAY['::character varying])::text[]"
DATA_B = "ARRAY[('::character varying)::text]"
INDEX = (
    "CREATE UNIQUE INDEX v13_lexing_index ON public.v13_lexing (marker) "
    "WHERE ((marker)::text = ANY ({}));"
)


def quoted(value):
    return "'" + value.replace("'", "''") + "'"


def escaped(value):
    # Deliberately retain physical newlines while escaping slash and single quote.
    return "E'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


class OpaqueSchemaLexingTests(SimpleTestCase):
    def assert_distinct_opaque(self, first, second, opaque_first, opaque_second):
        a, b = service.canonical_schema(first), service.canonical_schema(second)
        self.assertIn(opaque_first.encode(), a)
        self.assertIn(opaque_second.encode(), b)
        self.assertNotEqual(sha256(a).digest(), sha256(b).digest())

    def test_supported_array_cast_equivalence_survives_opaque_neighbors(self):
        # The same statement contains a real array expression and lookalike data.
        opaque = quoted("literal 'quote' " + DATA_A + " two  spaces")
        first = INDEX.format(LITERAL).removesuffix(";") + " AND marker <> " + opaque + ";"
        second = INDEX.format(DISTRIBUTED).removesuffix(";") + " AND marker <> " + opaque + ";"
        self.assertEqual(service.canonical_schema(first), service.canonical_schema(second))
        self.assertIn(opaque.encode(), service.canonical_schema(first))
        check = "    CONSTRAINT v13_allowed CHECK ((marker)::text = ANY ({}))"
        self.assertEqual(
            service.canonical_schema(check.format(LITERAL)),
            service.canonical_schema(check.format(DISTRIBUTED)),
        )

    def test_array_lookalikes_inside_quoted_values_and_identifiers_remain_distinct(self):
        for encode in (quoted, escaped, lambda x: "$payload$" + x + "$payload$", identifier):
            with self.subTest(encoding=encode.__name__):
                a, b = encode(DATA_A), encode(DATA_B)
                source = "CREATE INDEX v13_lexing_index ON public.v13_lexing(marker) WHERE marker <> {} ;"
                self.assert_distinct_opaque(source.format(a), source.format(b), a, b)
        # The opaque identifier occurs before WHERE, so scanning the whole index
        # line for a cast is also unsafe when WHERE itself is properly detected.
        a, b = identifier("idx " + DATA_A), identifier("idx " + DATA_B)
        source = "CREATE INDEX {} ON public.v13_lexing(marker) WHERE marker <> 'x';"
        self.assert_distinct_opaque(source.format(a), source.format(b), a, b)

    def test_escaped_and_doubled_quote_boundaries_do_not_end_strings_early(self):
        for encode in (quoted, escaped):
            prefix = "one ' quote, slash \\ and another '' quote\n"
            a, b = encode(prefix + DATA_A), encode(prefix + DATA_B)
            with self.subTest(encoding=encode.__name__):
                self.assert_distinct_opaque(INDEX.format(a), INDEX.format(b), a, b)
        a = identifier('embedded " quote\n' + DATA_A)
        b = identifier('embedded " quote\n' + DATA_B)
        self.assert_distinct_opaque(INDEX.format(a), INDEX.format(b), a, b)

    def test_literal_whitespace_and_line_endings_are_not_normalized(self):
        for first, second in (
            ("one  two", "one two"),
            ("one\ttwo", "one two"),
            ("one\r\ntwo", "one\ntwo"),
            ("one\rtwo", "one\ntwo"),
            ("one\n\ntwo", "one\ntwo"),
        ):
            for encode in (quoted, escaped, lambda x: "$value$" + x + "$value$"):
                a, b = encode(first), encode(second)
                with self.subTest(first=repr(first), encoding=encode.__name__):
                    self.assert_distinct_opaque(INDEX.format(a), INDEX.format(b), a, b)

    def test_nonce_commands_inside_strings_identifiers_and_dollar_bodies_are_data(self):
        payload = (
            "before\n\\restrict literal_nonce\n"
            + INDEX.format(LITERAL)
            + "\n\\unrestrict literal_nonce\nafter"
        )
        for encode in (
            quoted,
            escaped,
            identifier,
            lambda x: "$$" + x + "$$",
            lambda x: "$outer_tag$" + x + "$$ $inner$ -- */" + "$outer_tag$",
        ):
            value = encode(payload)
            source = "SELECT " + value + ";"
            with self.subTest(encoding=encode.__name__):
                self.assertIn(value.encode(), service.canonical_schema(source))
        body = "$fn$\nSELECT " + quoted(payload) + ";\n$fn$"
        source = "CREATE FUNCTION v13_lexing_function() RETURNS text LANGUAGE sql AS " + body + ";"
        self.assertIn(body.encode(), service.canonical_schema(source))
        outside_a = "\\restrict first_nonce\nSELECT 1;\n\\unrestrict first_nonce"
        outside_b = "\\restrict second_nonce\nSELECT 1;\n\\unrestrict second_nonce"
        self.assertEqual(service.canonical_schema(outside_a), service.canonical_schema(outside_b))
        self.assertNotIn(b"first_nonce", service.canonical_schema(outside_a))

    def test_nested_block_and_line_comments_are_opaque_without_masking_following_sql(self):
        block = (
            "/* outside\n/* nested $fake$ 'quote' */\n"
            + INDEX.format(LITERAL)
            + "\n\\restrict comment_nonce\n*/"
        )
        line = "-- " + INDEX.format(LITERAL) + " ' quote $$ /*"
        opaque = block + "\n" + line
        first = opaque + "\n" + INDEX.format(LITERAL)
        second = opaque + "\n" + INDEX.format(DISTRIBUTED)
        self.assertIn(opaque.encode(), service.canonical_schema(first))
        self.assertEqual(service.canonical_schema(first), service.canonical_schema(second))
        self.assertNotEqual(
            service.canonical_schema(first),
            service.canonical_schema(first.replace("comment_nonce", "different_comment")),
        )

    def test_different_dollar_tags_and_inner_quotes_do_not_close_outer_body(self):
        body = (
            "$outer$\nSELECT $$inner$$;\nSELECT $other$other$other$;\n"
            + INDEX.format(LITERAL)
            + "\n$outer$"
        )
        first = "CREATE FUNCTION v13_lexing_function() RETURNS text LANGUAGE sql AS " + body + ";"
        second = first.replace(LITERAL, DISTRIBUTED)
        self.assert_distinct_opaque(first, second, body, body.replace(LITERAL, DISTRIBUTED))

    def test_unterminated_opaque_tokens_fail_closed(self):
        for raw in (
            "SELECT 'unterminated",
            'SELECT "unterminated',
            "SELECT E'escaped\\'",
            "SELECT $open$unterminated",
            "/* outside /* nested */ still open",
        ):
            with self.subTest(raw=raw), self.assertRaises((service.RecoveryError, ValueError)):
                service.canonical_schema(raw)


class ActualDumpLexingTests(TransactionTestCase):
    def tools(self):
        # This lane does not silently skip missing PostgreSQL tools.
        return service.PostgresTools(os.environ["V12_PG_BIN"])

    def test_real_pg_dump_preserves_different_multiline_check_values(self):
        original, changed = "one\r\ntwo", "one\ntwo"
        database = connection.settings_dict["NAME"]
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE v13_lexing (marker text)")
        try:
            fingerprints, comparisons = [], []
            for value in (original, changed):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER TABLE v13_lexing DROP CONSTRAINT IF EXISTS v13_lexing_check"
                    )
                    cursor.execute(
                        "ALTER TABLE v13_lexing ADD CONSTRAINT v13_lexing_check CHECK (marker <> %s)",
                        [value],
                    )
                    cursor.execute("SELECT %s <> %s", [original, value])
                    comparisons.append(cursor.fetchone()[0])
                raw = self.tools().run("pg_dump", database, "--schema-only").decode()
                fingerprints.append(sha256(service.canonical_schema(raw)).hexdigest())
            self.assertEqual(comparisons, [False, True])
            self.assertNotEqual(*fingerprints)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE v13_lexing")

    def test_real_pg_dump_preserves_function_text_containing_nonce_and_index_lines(self):
        database = connection.settings_dict["NAME"]
        payload = "first\n\\restrict inside_function\n" + INDEX.format(LITERAL) + "\nlast"
        fingerprints, returned = [], []
        try:
            for value in (payload, payload.replace("inside_function", "changed_function")):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "CREATE OR REPLACE FUNCTION v13_lexing_value() RETURNS text LANGUAGE sql AS %s",
                        ["SELECT " + quoted(value)],
                    )
                    cursor.execute("SELECT v13_lexing_value()")
                    returned.append(cursor.fetchone()[0])
                raw = self.tools().run("pg_dump", database, "--schema-only").decode()
                normalized = service.canonical_schema(raw)
                self.assertIn(quoted(value).encode(), normalized)
                fingerprints.append(sha256(normalized).hexdigest())
            self.assertNotEqual(*returned)
            self.assertNotEqual(*fingerprints)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP FUNCTION IF EXISTS v13_lexing_value()")
