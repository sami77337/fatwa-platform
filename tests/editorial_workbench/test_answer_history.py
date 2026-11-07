"""An older answer keeps the exact source and wording its author saw."""

import os
import secrets
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import SimpleTestCase, override_settings

from apps.editorial_workbench import reviewer_settings as desk
from apps.fast9_case_source_join.answer_drafts import AUTHOR
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import (
    append_source_event,
    history_digest,
    save_answer_draft,
)


@override_settings(
    SETTINGS_MODULE=desk.__name__,
    ROOT_URLCONF=desk.ROOT_URLCONF,
    MIDDLEWARE=desk.MIDDLEWARE,
    ALLOWED_HOSTS=["127.0.0.1"],
)
class AnswerHistoryTests(SimpleTestCase):
    def test_search_and_compare_pinned_evidence_even_after_the_source_changes_again(self):
        token = secrets.token_hex(32)
        path = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(path),
                    "FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256": sha256(token.encode()).hexdigest(),
                },
            )
        )
        self.client.defaults["HTTP_HOST"] = "127.0.0.1"
        login = self.client.post(
            "/review/author/login/",
            urlencode({"token": token}),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(login.status_code, 303)

        received, corrected, restored = sample_source_events("intake-7", "restored")
        first_text = "عبارةٌ أولى\r\nمع <علامة>\t"

        def append(event):
            return append_source_event(path, event, synthetic_fixtures_only=True)

        def save(base, history, body):
            return save_answer_draft(
                path,
                author=AUTHOR,
                base_revision=base,
                count=len(history),
                source_digest=history_digest(history),
                reply_digest="",
                title="مسودة التدريب",
                body=body,
                evidence_seen=True,
                synthetic_fixtures_only=True,
            )

        save(0, append(received), first_text)
        corrected_history = append(corrected)
        save(1, corrected_history, first_text)
        save(2, corrected_history, "صياغةٌ جديدة")
        append(restored)

        url = "/review/author/history/"
        found = self.client.get(url, {"before": "1", "after": "2", "q": "عبارةٌ"})
        self.assertContains(found, "تطابق عنوان الجواب ونصه")
        self.assertContains(found, "اختلفت نسخة سجل السؤال")
        self.assertContains(found, "عبارةٌ أولى&#13;\nمع &lt;علامة&gt;\t")
        self.assertContains(found, "?from=2")
        self.assertEqual([row["item"].revision for row in found.context["history"]], [2, 1])
        self.assertEqual([e["source_count"] for e in found.context["evidence"]], [1, 2])
        self.assertContains(found, "تَصحيحٌ اصطناعيّ أوّل")
        compared = self.client.get(url, {"before": "2", "after": "3"})
        self.assertContains(compared, "<del>")
        self.assertContains(compared, "<ins>")
