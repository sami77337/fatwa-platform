"""Context is a bounded review locator; it never edits a citation or grants access."""

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases

from .models import TimedCitation
from .tests import SETTINGS, Fixture


@override_settings(**SETTINGS)
class PreviewContextTests(Fixture, TransactionTestCase):
    def test_context_is_clamped_to_verified_duration_and_original_stays_immutable(self):
        row = self.propose(start_ms=20, end_ms=60)
        original = TimedCitation.objects.get(pk=row["id"])
        before = (original.start_ms, original.end_ms, original.snapshot_sha256)
        preview = self.opened(row, review=True, context_ms=10)
        self.assertEqual((preview["preview_start_ms"], preview["preview_end_ms"]), (10, 70))
        self.assertEqual((preview["start_ms"], preview["end_ms"]), (20, 60))
        wide = self.opened(row, review=True, context_ms=5000)
        self.assertEqual((wide["preview_start_ms"], wide["preview_end_ms"]), (0, 100))
        self.assertEqual(wide["source_sha256"], self.pin["sha256"])
        self.assertEqual(wide["source_version"], self.pin["version"])
        self.assertEqual(wide["raw"], self.audio["raw"])
        original.refresh_from_db()
        self.assertEqual((original.start_ms, original.end_ms, original.snapshot_sha256), before)
        self.confirm(row)
        self.assertEqual(self.opened(row)["preview_start_ms"], 20)

    def test_context_does_not_bypass_scope_rights_confirmation_or_withdrawal(self):
        row = self.propose()
        for value in (-1, 5001, True, "10", 1.5):
            with self.subTest(value=value), self.assertRaises(cases.CaseConflict):
                self.opened(row, review=True, context_ms=value)
        with self.assertRaises(cases.CaseConflict):
            self.opened(row, context_ms=1000)
        self.rights.actions.remove("CITE")
        with self.assertRaises(cases.CaseConflict):
            self.opened(row, review=True, context_ms=1000)
        self.rights.actions.add("CITE")
        from . import services

        services.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        with self.assertRaises(cases.CaseConflict):
            self.opened(row, review=True, context_ms=1000)
