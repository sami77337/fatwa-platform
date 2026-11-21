import json
import tempfile
import unittest
from pathlib import Path

from django.db import connections
from django.test import TransactionTestCase, override_settings

from apps.casework.models import Case, CaseEvent
from apps.private_media.filesystem import FileSystemStorage
from apps.public_knowledge import recovery_support as knowledge_recovery
from apps.research_library.recovery_support import _canonical
from apps.research_workspace.tests import SETTINGS, ResearchFixture

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class TeachingRecoveryTests(TransactionTestCase):
    def test_fresh_connection_exact_nonempty_history_sources_and_current_trust_denials(self):
        with tempfile.TemporaryDirectory(prefix="teaching-recovery-") as folder:
            storage = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage):
                pins = json.loads(json.dumps(recovery_support.populate()))
                connections.close_all()
                result = recovery_support.verify_restored(pins)
                self.assertEqual(result["table_count"], 3)
                self.assertEqual(result["item_count"], 4)
                self.assertEqual(result["version_count"], 4)
                self.assertEqual(result["action_count"], 12)
                self.assertEqual(result["denied_read_count"], 6)
                self.assertTrue(result["positive_reads_after_denial"])
                self.assertTrue(result["source_and_teaching_rows_unchanged"])

    def test_teaching_population_after_advanced_research_seed_and_again_keeps_all_histories(self):
        class ResearchSeed(ResearchFixture, unittest.TestCase):
            pass

        with tempfile.TemporaryDirectory(prefix="teaching-composed-recovery-") as folder:
            storage = FileSystemStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(
                **{**SETTINGS, **FEATURES, "FATWA_PRIVATE_MEDIA_STORAGE": storage}
            ):
                seed = ResearchSeed()
                try:
                    seed.setUp()
                    seed.with_media()
                    research_id = seed.receipt["case_id"]
                    research_before = _canonical(research_id)
                    knowledge = knowledge_recovery.populate()
                    knowledge_before = _canonical(knowledge["case_id"])
                    first = recovery_support.populate()
                    first_ids = {row["case_id"] for row in first["cases"]}
                    self.assertNotIn(research_id, first_ids)
                    first_before = {identifier: _canonical(identifier) for identifier in first_ids}
                    second = recovery_support.populate()
                    second_ids = {row["case_id"] for row in second["cases"]}
                    self.assertFalse(first_ids & second_ids)
                    self.assertNotIn(research_id, second_ids)
                    self.assertNotIn(knowledge["case_id"], first_ids | second_ids)
                    self.assertEqual(
                        len({row["provider_id"] for row in (knowledge, first, second)}), 3
                    )
                    self.assertEqual(_canonical(research_id), research_before)
                    self.assertEqual(
                        {identifier: _canonical(identifier) for identifier in first_ids},
                        first_before,
                    )
                    self.assertEqual(Case.objects.count(), 6)
                    events = CaseEvent.objects.count()
                    self.assertTrue(
                        knowledge_recovery.verify_restored(knowledge)["original_source_preserved"]
                    )
                    for pins in (first, second):
                        result = recovery_support.verify_restored(pins)
                        self.assertEqual(result["denied_read_count"], 6)
                        self.assertTrue(result["source_and_teaching_rows_unchanged"])
                    self.assertEqual(CaseEvent.objects.count(), events)
                    self.assertEqual(_canonical(research_id), research_before)
                    self.assertEqual(_canonical(knowledge["case_id"]), knowledge_before)
                finally:
                    seed.doCleanups()
