"""Guarded reader adapter tests with real immutable DTOs; no database fixture."""

import os
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.intake_workflow import contracts as c
from apps.intake_workflow.review import (
    ReviewBatchOption,
    ReviewWorklist,
    StoredReviewEvent,
    StoredReviewRow,
)


def sample():
    timestamp = datetime(2026, 10, 24, tzinfo=timezone.utc)
    event = StoredReviewEvent(
        UUID(int=3),
        UUID(int=4),
        "start_review",
        "UNREVIEWED",
        "IN_REVIEW",
        "سبب اصطناعي",
        timestamp,
    )
    row = StoredReviewRow(
        UUID(int=2),
        UUID(int=1),
        1,
        "SYN-STORED",
        "  سؤالٌ\n  ",
        '{"question":"  سؤالٌ\\n  "}',
        10,
        40,
        "READY_FOR_EDITOR",
        "IN_REVIEW",
        None,
        (),
        (event,),
    )
    return ReviewWorklist(
        (ReviewBatchOption(UUID(int=1), timestamp),),
        UUID(int=1),
        (row,),
        row,
        1,
        1,
        1,
        1,
        20,
        "",
        "normalized",
        "",
        "",
    )


@override_settings(ALLOWED_HOSTS=["localhost"], WAVE7_READS_ENABLED=True)
class StoredAuditTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("editorial_workbench:stored")

    def get(self, suffix=""):
        return self.client.get(self.url + suffix, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")

    def test_guarded_reader_and_real_timeline_are_composed_without_snapshot_join(self):
        with (
            patch("apps.reference.services._workflow_reads_enabled", return_value=True),
            patch(
                "apps.intake_workflow.review.load_review_worklist", return_value=sample()
            ) as read,
        ):
            response = self.get("?batch=" + str(UUID(int=1)) + "&row=" + str(UUID(int=2)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [entry.kind for entry in response.context["timeline"]], ["batch", "review"]
        )
        self.assertTrue(read.call_args.kwargs["synthetic_fixtures_only"])
        self.assertContains(response, "SYN-STORED")
        self.assertContains(response, "event-" + str(UUID(int=3)))
        self.assertNotContains(response, "SYN-REVISION-COMPARE-001")

    def test_database_failure_is_helpful_and_does_not_expose_exception(self):
        with (
            patch("apps.reference.services._workflow_reads_enabled", return_value=True),
            patch(
                "apps.intake_workflow.review.load_review_worklist",
                side_effect=DatabaseError("PRIVATE-DSN"),
            ),
        ):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "PRIVATE-DSN", status_code=503)

    def test_query_validation_and_reader_errors_preserve_status(self):
        with (
            patch("apps.reference.services._workflow_reads_enabled", return_value=True),
            patch("apps.intake_workflow.review.load_review_worklist") as read,
        ):
            for query in ("?page=01", "?page=0", "?page_size=51", "?row=x&row=y", "?file=secret"):
                with self.subTest(query=query):
                    self.assertEqual(self.get(query).status_code, 400)
            read.assert_not_called()
            read.side_effect = c.ContractError("INVALID")
            self.assertEqual(self.get("?batch=bad").status_code, 400)

    def test_read_flag_is_not_enabled_by_a_query(self):
        with (
            patch.dict(os.environ, {"FATWA_WAVE7_SYNTHETIC_READS": "0"}),
            patch("apps.intake_workflow.review.load_review_worklist") as read,
        ):
            response = self.get("?enabled=1")
        self.assertEqual(response.status_code, 404)
        read.assert_not_called()
