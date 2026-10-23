"""Pure grouping of existing fixed synthetic report decisions and source slices."""

import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from apps.intake_workflow import contracts as c
from apps.reference_links.diagnostics import build_reference_diagnostics
from apps.reference_links.resolution import Heading


ROOT = Heading(
    7001, 1, "مرجع اصطناعي لتجارب Wave7", "كِتَابٌ اصطناعي", "الأول", 7,
    ("كِتَابٌ اصطناعي",), c.SOURCE_IDENTITY["source_namespace"], "622",
    c.SOURCE_IDENTITY["source_input_sha256"], c.SOURCE_IDENTITY["edition_key"],
    c.SOURCE_IDENTITY["source_archive_sha256"],
)
KNOWN = {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"}
UNKNOWN = {"source_id": "W7-SOURCE", "heading_id": "missing"}
MISMATCH = {**c.SOURCE_IDENTITY, "source_id": "wrong-synthetic-id"}


def report_for(items, rows=(ROOT,)):
    raw = json.dumps({
        "schema": c.PAYLOAD_SCHEMA, "synthetic_fixtures_only": True,
        "items": [{"reference_links": links} for links in items],
    }, ensure_ascii=False).encode("utf-8")
    return raw, build_reference_diagnostics(
        raw, synthetic_fixtures_only=True, catalog_rows=rows,
    )


class DiagnosticGroupTests(unittest.TestCase):
    def group(self, report):
        from apps.reference_links.diagnostic_groups import group_reference_diagnostics

        return group_reference_diagnostics(report, synthetic_fixtures_only=True)

    def test_partitions_exact_status_reason_tuples_once_per_reference(self):
        _, report = report_for([[UNKNOWN, MISMATCH], [UNKNOWN], [], [KNOWN]])
        result = self.group(report)
        self.assertIs(result.report, report)
        self.assertEqual(result.item_count, 4)
        self.assertEqual(result.reference_count, 4)
        self.assertEqual([
            (g.status.value, g.reasons, g.item_count, g.reference_count)
            for g in result.groups
        ], [
            ("MISMATCHED", ("source_identity_mismatch",), 1, 1),
            ("UNVERIFIED", ("explicit_mapping_missing",), 2, 2),
            ("VERIFIED", (), 1, 1),
        ])
        self.assertEqual([
            (member.item.row_ordinal, member.reference.reference_ordinal)
            for member in result.groups[1].members
        ], [(1, 1), (2, 1)])

    def test_locators_retain_exact_original_objects_hashes_and_ordinals(self):
        raw, report = report_for([[KNOWN, UNKNOWN], [UNKNOWN]])
        result = self.group(report)
        for group in result.groups:
            for member in group.members:
                item, reference = member.item, member.reference
                self.assertIs(item, report.items[item.row_ordinal - 1])
                self.assertIs(reference, item.references[reference.reference_ordinal - 1])
                self.assertEqual(member.locator, (
                    hashlib.sha256(raw).hexdigest(), item.row_ordinal,
                    reference.reference_ordinal,
                ))
                self.assertEqual(member.item_source_sha256, hashlib.sha256(
                    raw[item.source.start:item.source.end]).hexdigest())
                self.assertEqual(member.reference_source_sha256, hashlib.sha256(
                    raw[reference.source.start:reference.source.end]).hexdigest())
                self.assertEqual(raw[reference.source.start:reference.source.end],
                                 reference.source.text.encode("utf-8"))
        # Repeated source IDs are distinct occurrences, with different locators.
        unresolved = result.groups[0].members
        self.assertEqual(len({m.locator for m in unresolved}), 2)
        self.assertEqual(len({m.reference_source_sha256 for m in unresolved}), 1)

    def test_multiple_reasons_are_one_group_and_do_not_inflate_counts(self):
        _, report = report_for([[UNKNOWN, MISMATCH], [UNKNOWN]])
        reasons = ("identity_not_found", "multiple_exact_candidates", "identity_not_found")
        refs = tuple(replace(ref, status=c.ReferenceStatus.UNVERIFIED, reasons=reasons)
                     for ref in report.items[0].references)
        first = replace(report.items[0], references=refs)
        report = replace(report, items=(first, report.items[1]))
        result = self.group(report)
        self.assertEqual(result.reference_count, 3)
        self.assertEqual([(g.reasons, g.item_count, g.reference_count) for g in result.groups], [
            (("explicit_mapping_missing",), 1, 1), (reasons, 1, 2),
        ])
        self.assertIs(result.groups[1].reasons, reasons)

    def test_ambiguous_absent_and_conflicting_evidence_keep_original_decisions(self):
        for rows, expected_status, reason in (
            ((), c.ReferenceStatus.UNVERIFIED, "identity_not_found"),
            ((ROOT, ROOT), c.ReferenceStatus.UNVERIFIED, "multiple_exact_candidates"),
            ((replace(ROOT, printed_page=99),), c.ReferenceStatus.MISMATCHED,
             "catalog_metadata_mismatch"),
        ):
            with self.subTest(reason=reason):
                _, report = report_for([[KNOWN]], rows)
                group, = self.group(report).groups
                self.assertEqual((group.status, group.reasons), (expected_status, (reason,)))
                self.assertIs(group.members[0].reference, report.items[0].references[0])
                self.assertIsNone(group.members[0].reference.evidence)
                self.assertEqual(group.members[0].reference.identity, ())

    def test_order_is_stable_even_when_report_containers_are_reordered(self):
        _, report = report_for([[MISMATCH, UNKNOWN], [UNKNOWN], [KNOWN]])
        reordered = replace(report, items=tuple(
            replace(item, references=tuple(reversed(item.references)))
            for item in reversed(report.items)
        ))
        def signature(result):
            return [(g.status, g.reasons, tuple(m.locator for m in g.members))
                    for g in result.groups]

        self.assertEqual(signature(self.group(report)), signature(self.group(reordered)))

    def test_no_reference_items_have_exact_counts_and_no_groups(self):
        _, report = report_for([[], []])
        result = self.group(report)
        self.assertEqual(result.groups, ())
        self.assertEqual((result.item_count, result.reference_count), (2, 0))

    def test_duplicate_pointers_count_occurrences_without_collapsing_source_ids(self):
        _, report = report_for([[KNOWN, KNOWN], [KNOWN]])
        unresolved, verified = self.group(report).groups
        self.assertEqual((unresolved.reasons, unresolved.item_count,
                          unresolved.reference_count), (("duplicate_pointer",), 1, 2))
        self.assertEqual([m.locator[1:] for m in unresolved.members], [(1, 1), (1, 2)])
        self.assertEqual((verified.item_count, verified.reference_count), (1, 1))
        self.assertIs(verified.members[0].reference.evidence, ROOT)

    def test_projection_containers_are_frozen_and_report_is_unchanged(self):
        _, report = report_for([[UNKNOWN]])
        before = report.json_bytes()
        result = self.group(report)
        for obj, field, value in (
            (result, "groups", ()), (result.groups[0], "members", ()),
            (result.groups[0].members[0], "locator", ("changed", 0, 0)),
        ):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(obj, field, value)
        self.assertEqual(report.json_bytes(), before)

    def test_literal_acknowledgement_is_required_before_reading_report(self):
        from apps.reference_links.diagnostic_groups import group_reference_diagnostics

        for ack in (False, None, 1, "true", []):
            with self.subTest(ack=ack), self.assertRaisesRegex(
                c.ContractError, "synthetic_acknowledgement_required"
            ):
                group_reference_diagnostics(object(), synthetic_fixtures_only=ack)
        with self.assertRaisesRegex(c.ContractError, "diagnostic_report_required"):
            self.group(object())

    def test_grouping_performs_no_io_or_new_resolution(self):
        from django.db.backends.base.base import BaseDatabaseWrapper
        from apps.reference_links.diagnostic_groups import group_reference_diagnostics

        _, report = report_for([[UNKNOWN, MISMATCH], [KNOWN]])
        with patch("builtins.open", side_effect=AssertionError("file I/O")), \
             patch("socket.socket", side_effect=AssertionError("network I/O")), \
             patch.object(BaseDatabaseWrapper, "connect", side_effect=AssertionError("DB connect")), \
             patch.object(BaseDatabaseWrapper, "cursor", side_effect=AssertionError("DB query")), \
             patch("apps.intake_workflow.references.plan_reference_verification",
                   side_effect=AssertionError("new planning")), \
             patch("apps.intake_workflow.references.resolve",
                   side_effect=AssertionError("new resolution")), \
             patch.object(type(report), "to_payload", side_effect=AssertionError("serialization")):
            result = group_reference_diagnostics(report, synthetic_fixtures_only=True)
        self.assertEqual(result.reference_count, 3)
