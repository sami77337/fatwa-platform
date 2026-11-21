"""Synthetic original text and explicitly scoped fixture authorities only."""

import uuid
from dataclasses import replace

from django.test import override_settings

from apps.casework import services as cases
from apps.research_library.test_support import FEATURES as LIBRARY_FEATURES
from apps.research_library.test_support import LibraryFixture, payload

from . import services, sources
from .authority import CitationAuthority
from .boundary import scope

FEATURES = {
    **LIBRARY_FEATURES,
    "FATWA_PRECISE_CITATIONS_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 40,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
}


class FixtureAuthority(CitationAuthority):
    def __init__(self, *refs):
        self.refs, self.denied, self.hook = set(refs), set(), None

    def projection_epoch(self):
        return repr((sorted(self.refs), sorted(self.denied, key=repr)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"]
            in {"READ", "EDIT", "REVIEW", "EXPORT", "CITE_SOURCE", "READ_SOURCE", "EXPORT_SOURCE"}
            and values["action"] not in self.denied
            and (values["action"], values["resource_id"]) not in self.denied
        )


class CitationFixture(LibraryFixture):
    def setUp(self):
        super().setUp()
        self.citation_authority = FixtureAuthority(self.receipt["public_ref"])
        configured = override_settings(FATWA_PRECISE_CITATIONS_AUTHORITY=self.citation_authority)
        configured.enable()
        self.addCleanup(configured.disable)
        self.material = self.approve(
            self.write(
                payload=payload(recorded_text="مصدر اصطناعي دقيق محفوظ للإحالة"),
                file_bytes="مصدر اصطناعي دقيق محفوظ للإحالة".encode(),
                filename="source.txt",
                media_type="text/plain",
            )
        )
        self.answer_text = "تمهيد ثم عبارة محددة ثم عبارة محددة."

    def selection(self, *, base=None, material=None):
        base = base or self.common
        with scope(**base) as guard:
            pin, _ = sources.select(
                guard,
                "LIBRARY:" + (material or self.material)["version_id"],
                owner_case_id=base["case_id"],
                location=sources.locator("TEXT", 0, 12),
            )
        at = services.occurrences(self.answer_text, "عبارة محددة")[1]
        return services.anchor(
            self.answer_text, start=at["start"], end=at["end"], phrase="عبارة محددة", source=pin
        )

    def save_citations(self, **changes):
        values = dict(
            self.common,
            text=self.answer_text,
            selections=[self.selection()],
            expected_revision=1,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        return services.save(**{**values, **changes})

    def review_citations(self, row, **changes):
        values = dict(
            self.common,
            subject_id="other",
            set_id=row["id"],
            action="APPROVE",
            note="راجعت الموضع والنسخة",
            expected_revision=2,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        return services.review(**{**values, **changes})

    def second_case(self):
        key = uuid.uuid4().hex
        receipt = cases.intake_case(
            original_question="سؤال اصطناعي ثانٍ",
            source_event_id=key,
            requester_id="private-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=actor.case_keys | {receipt["public_ref"]}
            )
        self.authority.refs.add(receipt["public_ref"])
        self.citation_authority.refs.add(receipt["public_ref"])
        return receipt, {**self.common, "case_id": receipt["case_id"]}
