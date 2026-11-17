"""Cross-lane tests, runnable only when the coordinator installs V11 C's app.

No C files are copied into this lane. Missing C explicitly skips these tests;
normal workspace default-deny tests still apply in the isolated lane.
"""

from dataclasses import replace
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from tests.reference.test_catalog import fixture

from . import services
from .rights import Resource
from .source_rights_adapter import SourceRightsAdapter
from .tests import SETTINGS, ResearchFixture


@skipUnless(apps.is_installed("apps.source_rights"), "V11 C app must be installed by integration")
@override_settings(**SETTINGS, FATWA_SOURCE_RIGHTS_ENABLED=True)
class SourceRightsIntegrationTests(ResearchFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        from apps.source_rights import services as ledger
        from apps.source_rights.tests import Authority

        self.ledger = ledger
        overlay = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
        )
        overlay.enable()
        self.addCleanup(overlay.disable)

    def grant(self, *, row=2, uses=("READ", "CITE", "RELATE"), transcript=False, number=0):
        target = (
            self.transcript["link_id"]
            if transcript
            else ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=row).pk
        )
        source = self.ledger.register(
            **self.common,
            kind="PRIVATE_TRANSCRIPT" if transcript else "TOC_METADATA",
            target_id=target,
        )
        proposal = self.ledger.propose(
            **self.common,
            source_id=source["id"],
            expected_number=number,
            uses=list(uses),
            basis="Explicit synthetic documentary basis",
            note="human review",
            ttl_minutes=60,
        )
        self.ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=proposal["id"],
            action="APPROVE",
            confirmed=True,
            note="independent synthetic review",
        )
        return proposal

    def test_exact_read_cite_expiry_revocation_and_no_edition_inheritance(self):
        self.assertEqual(self.search()["editions"], [])
        self.grant(row=2)
        allowed = self.grant(row=3, uses=("READ",))
        found = self.search(kind="REFERENCE", edition_id=self.catalog_id, query="فرع")
        self.assertEqual([r["source"]["source_row_id"] for r in found["results"]], [2])
        services.open_resource(**self.common, resource=self.source(3))
        with self.assertRaises(cases.CaseConflict):
            self.add()  # READ does not confer CITE.
        self.grant(row=3, number=1)
        self.add()  # Current CITE on both the retained and new reference.
        spec, rows = fixture()
        spec = replace(
            spec,
            source_book_id="622",
            edition_key="different-edition",
            source_archive_sha256="c" * 64,
            source_input_sha256="d" * 64,
        )
        preview = ingest_catalog(spec, rows)
        second = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        with self.assertRaises(cases.CaseConflict):
            self.search(kind="REFERENCE", edition_id=second, query="فرع")
        # Advance the ledger clock with a valid short-lived actor at that time;
        # restore both together, preserving the identity provider's one-hour cap.
        future = timezone.now() + timedelta(hours=2)
        with (
            patch.dict(
                self.directory.identities,
                {
                    "editor": replace(
                        self.directory.identities["editor"],
                        valid_until=future + timedelta(minutes=30),
                    )
                },
            ),
            patch.object(self.ledger.timezone, "now", return_value=future),
        ):
            self.assertEqual(self.search()["editions"], [])
        # A new approved restriction closes the current source; history cannot grant.
        restricted = self.grant(row=3, uses=(), number=2)
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=self.source(3))
        self.assertNotEqual(allowed["id"], restricted["id"])

    def test_transcript_and_knowledge_require_current_read_and_relate(self):
        self.assertEqual(self.search(kind="TRANSCRIPT")["results"], [])
        self.grant(transcript=True, uses=("READ",))
        resource = Resource(**self.search(kind="TRANSCRIPT")["results"][0]["resource"])
        self.assertEqual(
            services.open_resource(**self.common, resource=resource)["question"]["text"],
            self.transcript_text,
        )
        relation = self.propose("TRANSCRIPT")
        self.approve(relation)
        self.assertEqual(self.search(kind="KNOWLEDGE")["results"], [])
        approved = self.grant(transcript=True, uses=("READ", "RELATE"), number=1)
        self.assertEqual(len(self.search(kind="KNOWLEDGE")["results"]), 1)
        self.ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=approved["id"],
            action="REVOKE",
            confirmed=True,
            note="synthetic revocation",
        )
        self.assertEqual(self.search(kind="TRANSCRIPT")["results"], [])
        self.assertEqual(self.search(kind="KNOWLEDGE")["results"], [])
        with self.assertRaises(cases.CaseConflict):
            services.open_resource(**self.common, resource=resource)

    def test_ledger_does_not_infer_case_media_rights(self):
        self.with_media()
        self.assertEqual(self.search(kind="MEDIA")["results"], [])
        with override_settings(
            FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(media_rights=self.rights)
        ):
            rows = self.search(kind="MEDIA")["results"]
            self.assertEqual(len(rows), 1)
            self.rights.denied.add(("ANSWER_MEDIA", "READ_MEDIA"))
            with self.assertRaises(cases.CaseConflict):
                services.open_resource(**self.common, resource=Resource(**rows[0]["resource"]))
