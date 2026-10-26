"""Deterministic negative checks against the real ingest contract, without DB I/O."""

import unicodedata
from copy import deepcopy
from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock

from apps.fast9_pg_reference_consistency.services import (
    CatalogReadUnavailable,
    check_catalog,
)
from apps.reference.records import prepare_catalog
from tools.fast9_pg_reference_consistency.fixtures import synthetic_fixture

from .support import EDITION_ID, snapshot


class ConsistencyTests(TestCase):
    def setUp(self):
        self.pin = synthetic_fixture()
        self.rows = snapshot()
        self.reader = Mock()
        self.reader.read.return_value = self.rows

    def check(self):
        return check_catalog(self.pin, EDITION_ID, self.reader)

    def assert_rejected(self, status="INCONSISTENT"):
        result = self.check()
        self.assertEqual(result.status, status)
        self.assertEqual(result.checked_rows, 0)
        self.assertIsNone(result.ingest_checksum)
        self.assertEqual(result.source_acceptance, "NOT_CONNECTED")

    def test_exact_unicode_source_order_and_printed_metadata_match_without_mutation(self):
        before = deepcopy(self.rows)
        result = self.check()
        self.assertEqual(result.status, "CONSISTENT")
        self.assertEqual(result.checked_rows, 4)
        self.assertEqual(result.ingest_checksum, self.pin.checksum)
        self.assertEqual(result.source_acceptance, "NOT_CONNECTED")
        self.assertEqual(self.rows, before)
        self.assertIn("\r\n", self.pin.records[0].title_original)
        self.assertNotEqual(
            self.pin.records[0].title_original,
            unicodedata.normalize("NFC", self.pin.records[0].title_original),
        )

    def test_no_reader_is_not_connected(self):
        self.assertEqual(check_catalog(self.pin, EDITION_ID).status, "NOT_CONNECTED")

    def test_invalid_ids_and_forged_pins_never_call_reader(self):
        for ident in (True, None, 0, -1, "7009", 1.0, 2**63):
            with self.subTest(ident=ident):
                self.assertEqual(check_catalog(self.pin, ident, self.reader).reason, "invalid_pin")
        for pin in (
            None,
            replace(self.pin, checksum="0" * 64),
            replace(self.pin, records=tuple(reversed(self.pin.records))),
            replace(self.pin, records=()),
            replace(self.pin, records=self.pin.records * 5001),
            replace(self.pin, spec=replace(self.pin.spec, expected_rows=True)),
        ):
            with self.subTest(pin_type=type(pin)):
                self.assertEqual(check_catalog(pin, EDITION_ID, self.reader).reason, "invalid_pin")
        self.reader.read.assert_not_called()

    def test_absent_extra_and_duplicate_work_edition_or_heading_rejected(self):
        for part in ("works", "editions", "headings"):
            values = getattr(self.rows, part)
            for altered in (values[:-1], values + (values[-1],)):
                with self.subTest(part=part, count=len(altered)):
                    self.reader.read.return_value = replace(self.rows, **{part: altered})
                    status = (
                        "NOT_CONNECTED" if part != "headings" and not altered else "INCONSISTENT"
                    )
                    self.assert_rejected(status)

    def test_every_work_and_edition_field_is_pinned(self):
        for part in ("works", "editions"):
            record = getattr(self.rows, part)[0]
            for key, original in record.items():
                with self.subTest(part=part, key=key):
                    # Work PK is a local identity, not a source pin; its edition FK binds it.
                    record[key] = original + 1 if type(original) is int else original + "changed"
                    self.assert_rejected(
                        "NOT_CONNECTED" if part == "editions" and key == "id" else "INCONSISTENT"
                    )
                    record[key] = original

    def test_every_heading_field_and_parent_join_is_compared(self):
        record = self.rows.headings[1]
        for key, original in tuple(record.items()):
            if key == "id":
                continue  # leaf local PK has no externally pinned meaning
            with self.subTest(key=key):
                record[key] = original + 1 if type(original) is int else str(original) + "changed"
                self.assert_rejected()
                record[key] = original

    def test_reordered_rows_and_duplicate_physical_ids_rejected(self):
        self.reader.read.return_value = replace(
            self.rows, headings=tuple(reversed(self.rows.headings))
        )
        self.assert_rejected()
        self.reader.read.return_value = self.rows
        self.rows.headings[1]["id"] = self.rows.headings[0]["id"]
        self.assert_rejected()

    def test_nfc_trimming_or_line_ending_rewrites_are_not_equivalent(self):
        original = self.rows.headings[0]["title_original"]
        for changed in (
            unicodedata.normalize("NFC", original),
            original.strip(),
            original.replace("\r\n", "\n"),
        ):
            with self.subTest(changed=repr(changed)):
                self.rows.headings[0]["title_original"] = changed
                self.assert_rejected()

    def test_same_row_id_from_foreign_edition_is_rejected(self):
        self.rows.headings[1]["parent__edition_id"] += 1
        self.assert_rejected()

    def test_null_missing_or_forged_parent_pk_is_rejected(self):
        for value in (None, 9999, True):
            with self.subTest(value=value):
                self.rows.headings[1]["parent_id"] = value
                self.assert_rejected()

    def test_unknown_fields_and_bool_integer_aliases_are_rejected(self):
        self.rows.headings[0]["depth"] = True
        self.assert_rejected()
        self.rows.headings[0]["depth"] = 1
        self.rows.headings[0]["unexpected"] = "no implicit fields"
        self.assert_rejected()

    def test_self_consistent_replacement_cannot_replace_independent_pin(self):
        changed = prepare_catalog(
            replace(self.pin.spec, work_title="عنوان اصطناعي بديل"),
            self.pin.records,
        )
        self.rows.works[0]["title_original"] = changed.spec.work_title
        self.rows.editions[0]["ingest_checksum"] = changed.checksum
        self.assert_rejected()

    def test_malformed_snapshot_and_missing_fields_rejected(self):
        for malformed in (None, {}, replace(self.rows, headings=list(self.rows.headings))):
            self.reader.read.return_value = malformed
            self.assert_rejected()
        self.reader.read.return_value = self.rows
        del self.rows.headings[0]["source_row_id"]
        self.assert_rejected()

    def test_unavailable_reader_does_not_disclose_details(self):
        self.reader.read.side_effect = CatalogReadUnavailable("SYNTHETIC_SECRET_SENTINEL")
        result = self.check()
        self.assertEqual(result.status, "NOT_CONNECTED")
        self.assertNotIn("SYNTHETIC_SECRET_SENTINEL", repr(result))
