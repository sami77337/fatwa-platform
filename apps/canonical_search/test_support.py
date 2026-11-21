"""Explicit synthetic identities and canonical service-created text only."""

import uuid
from dataclasses import replace

from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.tests import Directory
from apps.knowledge_links.tests import Authority as BaseKnowledgeAuthority
from apps.research_library.test_support import bind_identity_snapshot
from apps.research_workspace.tests import SyntheticRights
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.tests import bundle
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .authority import SearchAuthority
from .models import SearchGeneration

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_CANONICAL_SEARCH_ENABLED": True,
    "FATWA_RESEARCH_WORKSPACE_ENABLED": True,
    "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


class FixtureAuthority(SearchAuthority):
    def __init__(self, *refs):
        self.refs, self.denied, self.hook, self.calls = set(refs), set(), None, []

    def projection_epoch(self):
        return repr((sorted(self.refs), sorted(self.denied)))

    def permits(self, **values):
        self.calls.append(values)
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"] in {"VIEW", "SEARCH", "REBUILD", "OPEN"}
            and values["action"] not in self.denied
        )


class KnowledgeAuthority(BaseKnowledgeAuthority):
    def projection_epoch(self):
        return repr((self.ref, self.allow_open))


class SearchFixture:
    def setUp(self):
        super().setUp()
        self.question = "  سُؤالٌ اصطناعيّ عن الزَّكَاةِ؛ المُعاملاتِ المالية\r\nكما كُتب  "
        self.receipt = self.new_case(self.question)
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.authority = FixtureAuthority(self.receipt["public_ref"])
        self.rights = SyntheticRights(self.receipt["public_ref"])
        self.knowledge = KnowledgeAuthority(self.receipt["public_ref"])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        configured = override_settings(
            FATWA_CANONICAL_SEARCH_AUTHORITY=self.authority,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_KNOWLEDGE_LINKS_AUTHORITY=self.knowledge,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def new_case(self, text):
        key = uuid.uuid4().hex
        return cases.intake_case(
            original_question=text,
            source_event_id=key,
            requester_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )

    def grant(self, *refs):
        self.authority.refs.update(refs)
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=actor.case_keys | frozenset(refs)
            )

    def build(self, **changes):
        base = {**self.common, **changes}
        case = Case.objects.get(pk=base["case_id"])
        generation = SearchGeneration.objects.filter(case=case).order_by("-number").first()
        return services.rebuild(
            **base,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_generation=generation.number if generation else 0,
            request_key=uuid.uuid4(),
        )

    def answer(self, text="جواب اصطناعي محفوظ عن المُعاملات المالية"):
        case = Case.objects.get(pk=self.common["case_id"])
        return cases.save_answer(
            **self.common,
            text=text,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )

    def transcript(self):
        preview = transcripts.preview(**self.common, bundle=bundle())
        link = transcripts.attach(
            **self.common,
            upload_id=preview["upload_id"],
            external_id=preview["entries"][0].external_id,
        )
        return link, preview["entries"][0]

    def search(self, value="زكاة", **changes):
        return services.search(**self.common, value=value, **changes)
