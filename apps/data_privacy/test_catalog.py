"""Closed identities for independently consumed scholarly source versions."""

from django.test import TransactionTestCase, override_settings

from apps.knowledge_links.models import KnowledgeRevision
from apps.knowledge_links.tests import FEATURES as KNOWLEDGE_FEATURES
from apps.knowledge_links.tests import Fixture as KnowledgeFixture
from apps.scholarly_links.tests import FEATURES as SCHOLARLY_FEATURES
from apps.scholarly_links.tests import Fixture as ScholarlyFixture

from .catalog import digest, locate


@override_settings(**SCHOLARLY_FEATURES)
class ScholarlyCatalogTests(ScholarlyFixture, TransactionTestCase):
    def test_series_and_lesson_have_separate_exact_version_identities(self):
        series = self.series()
        lesson = self.lesson(series=series)
        targets = [locate("SERIES_VERSION", series.pk), locate("LESSON_VERSION", lesson.pk)]
        for target, row in zip(targets, (series, lesson), strict=True):
            self.assertEqual(target.case_id, str(self.receipt["case_id"]))
            self.assertEqual(target.case_ref, self.receipt["public_ref"])
            self.assertEqual(
                target.source_digest,
                digest([target.kind, str(row.pk), row.sha256, target.case_id]),
            )
        self.assertNotEqual(targets[0].source_digest, targets[1].source_digest)


@override_settings(**KNOWLEDGE_FEATURES)
class KnowledgeCatalogTests(KnowledgeFixture, TransactionTestCase):
    def test_knowledge_revision_has_its_own_source_pin_and_case(self):
        revision = KnowledgeRevision.objects.get(pk=self.propose()["id"])
        target = locate("KNOWLEDGE_REVISION", revision.pk)
        self.assertEqual(target.case_id, str(self.receipt["case_id"]))
        self.assertEqual(target.case_ref, self.receipt["public_ref"])
        self.assertEqual(
            target.source_digest,
            digest([target.kind, str(revision.pk), revision.snapshot_sha256, target.case_id]),
        )
