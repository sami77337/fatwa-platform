"""Explicit synthetic dictionary permissions; no production vocabulary or grants."""

import uuid
from copy import deepcopy

from django.test import override_settings

from apps.casework.models import Case

from . import governance
from .governance_pins import ACTIONS
from .models import SynonymDecision, SynonymRevision
from .test_support import FEATURES as SEARCH_FEATURES
from .test_support import FixtureAuthority, SearchFixture

FEATURES = {
    **SEARCH_FEATURES,
    "FATWA_SEARCH_GOVERNANCE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 128,
}
TERM = "مرادفاصطناعي"
ENTRIES = [{"key": "synthetic-one", "term": TERM, "alternatives": ["المعاملات"]}]
CREDENTIALS = {
    "editor": "synthetic-editor-credential-32-characters",
    "other": "synthetic-reviewer-credential-32-characters",
}


class GovernanceAuthority(FixtureAuthority):
    def permits(self, **values):
        self.calls.append(values)
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"] in {"VIEW", "SEARCH", "REBUILD", "OPEN"} | ACTIONS
            and values["action"] not in self.denied
        )


class GovernanceFixture(SearchFixture):
    def setUp(self):
        super().setUp()
        self.authority = GovernanceAuthority(self.receipt["public_ref"])
        self.directory.authenticate = lambda credential: next(
            (
                self.directory.resolve(subject)
                for subject, key in CREDENTIALS.items()
                if credential == key
            ),
            None,
        )
        configured = override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=self.authority)
        configured.enable()
        self.addCleanup(configured.disable)
        self.answer()
        self.build()

    def pins(self):
        case = Case.objects.get(pk=self.common["case_id"])
        return {
            "expected_revision": case.revision,
            "expected_evidence_version": case.evidence_version,
        }

    def revision(self, **changes):
        previous = (
            SynonymRevision.objects.filter(case_id=self.common["case_id"])
            .order_by("-number")
            .first()
        )
        values = {
            **self.common,
            **self.pins(),
            "expected_number": previous.number if previous else 0,
            "request_key": uuid.uuid4(),
            "title": "قاموس اصطناعي لتجربة الاسترجاع فقط",
            "provenance": "ألفاظ اختبارية صُنعت لهذه التجربة، بلا اعتماد مرادفات شرعية.",
            "entries": deepcopy(ENTRIES),
            "mapping": [
                {
                    "from": row["key"],
                    "kind": "SAME",
                    "to": [row["key"]],
                    "reason": "استمرار المعرف نفسه في تجربة جديدة",
                }
                for row in previous.entries
            ]
            if previous
            else [],
        }
        return governance.create_revision(**{**values, **changes})

    def preview(self, revision, **changes):
        return governance.prepare_preview(
            **{
                **self.common,
                **self.pins(),
                "revision_id": revision["id"],
                "queries": [TERM, "المعاملات"],
                "request_key": uuid.uuid4(),
                **changes,
            }
        )

    def decide(self, revision, preview=None, **changes):
        latest = (
            SynonymDecision.objects.filter(revision_id=revision["id"]).order_by("-sequence").first()
        )
        return governance.decide(
            **{
                **self.common,
                **self.pins(),
                "subject_id": "other",
                "revision_id": revision["id"],
                "preview_id": preview["id"] if preview else None,
                "action": "APPROVE",
                "note": "مراجعة بشرية مستقلة للألفاظ الاصطناعية وأثر الاسترجاع",
                "ttl_minutes": 60,
                "expected_sequence": latest.sequence if latest else 0,
                "request_key": uuid.uuid4(),
                "confirmed": True,
                **changes,
            }
        )

    def approved(self):
        revision = self.revision()
        preview = self.preview(revision)
        self.decide(revision, preview)
        return revision, preview

    def shadow(self, revision, **changes):
        return governance.run_shadow(
            **{
                **self.common,
                **self.pins(),
                "revision_id": revision["id"],
                "value": TERM,
                "request_key": uuid.uuid4(),
                **changes,
            }
        )
