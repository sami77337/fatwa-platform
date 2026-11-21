"""The last maintenance callback must precede every retained owner/source pure check."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.ai_gateway import services as gateway
from apps.ai_gateway.models import CandidateBatch, GatewayOutcome
from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument, SearchGeneration
from apps.casework import services as cases

from .models import DerivativeRebuild
from .test_support import FEATURES, Fixture


@override_settings(**FEATURES)
class LastMaintenanceCallbackTests(Fixture, TransactionTestCase):
    def ai_after_terminal(self, revoke, restore):
        self.change(kind="AI_CANDIDATES")
        original, succeeded, fired = gateway.terminal, False, False

        def terminal(run, status, entries=None):
            nonlocal succeeded
            value = original(run, status, entries)
            if status == "SUCCEEDED":
                succeeded = True
            return value

        def late(values):
            nonlocal fired
            if succeeded and values["action"] == "REBUILD":
                fired = True
                revoke()

        self.maintenance_authority.hook = late
        with patch.object(gateway, "terminal", side_effect=terminal):
            with self.assertRaises(cases.CaseConflict):
                self.change("REBUILD", "AI_CANDIDATES")
        self.assertTrue(succeeded)
        self.assertTrue(fired)
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(DerivativeRebuild.objects.count(), 0)
        self.assertEqual(GatewayOutcome.objects.filter(status="REVOKED").count(), 1)
        self.maintenance_authority.hook = None
        restore()
        result = self.change("REBUILD", "AI_CANDIDATES")
        self.assertEqual(result["status"], "SUCCEEDED")
        with gateway.read_boundary(**self.common, run_id=result["child_id"]) as current:
            self.assertEqual(len(current["candidates"]), 1)

    def test_last_maintenance_callback_revokes_ai_use_after_terminal(self):
        self.ai_after_terminal(
            lambda: self.gateway_authority.denied.add(("USE", "CASE")),
            self.gateway_authority.denied.clear,
        )

    def test_last_maintenance_callback_revokes_source_processing_after_terminal(self):
        self.ai_after_terminal(
            lambda: self.gateway_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY")),
            self.gateway_authority.denied.clear,
        )

    def test_last_maintenance_callback_revokes_source_read_after_terminal(self):
        self.ai_after_terminal(
            lambda: self.authority.denied.add("READ"), self.authority.denied.clear
        )

    def test_last_maintenance_callback_revokes_source_cite_after_terminal(self):
        self.ai_after_terminal(
            lambda: self.authority.denied.add("CITE"), self.authority.denied.clear
        )

    def test_last_maintenance_callback_revokes_search_rebuild_before_outer_commit(self):
        self.change()
        original, built, fired = search.rebuild, False, False

        def rebuild(**values):
            nonlocal built
            result = original(**values)
            built = True
            return result

        def late(values):
            nonlocal fired
            if built and values["action"] == "REBUILD":
                fired = True
                self.search_authority.denied.add("REBUILD")

        self.maintenance_authority.hook = late
        with patch.object(search, "rebuild", side_effect=rebuild):
            with self.assertRaises(cases.CaseConflict):
                self.change("REBUILD")
        self.assertTrue(built)
        self.assertTrue(fired)
        self.assertEqual(SearchGeneration.objects.count(), 1)
        self.assertEqual(SearchDocument.objects.count(), 0)
        self.assertEqual(DerivativeRebuild.objects.count(), 0)
        self.maintenance_authority.hook = None
        self.search_authority.denied.clear()
        self.change("REBUILD")
        self.assertGreater(search.search(**self.common, value="اصطناعي")["total"], 0)
