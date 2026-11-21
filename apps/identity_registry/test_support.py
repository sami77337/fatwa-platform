"""Fabricated providers and people; no actual identity evidence or accounts."""

import uuid
from dataclasses import replace

from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_case_intake import services as intake
from apps.source_case_intake import simulators
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .authority import IdentityAuthority

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_IDENTITY_REGISTRY_ENABLED": True,
    "FATWA_SOURCE_CASE_INTAKE_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 96,
}


class Authority(IdentityAuthority):
    def __init__(self, refs):
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
            in {
                "READ",
                "SEARCH",
                "CAPTURE",
                "CREATE_PERSON",
                "LINK",
                "VERIFY",
                "UNLINK",
                "MERGE",
                "SPLIT",
                "AUDIT",
            }
            and values["action"] not in self.denied
            and (values["action"], values["case_ref"]) not in self.denied
        )


class RegistryFixture:
    def setUp(self):
        super().setUp()
        self.receipt = intake.ingest(
            raw=simulators.telegram(),
            context=simulators.context(
                "telegram", account="synthetic-identity-" + uuid.uuid4().hex
            ),
            synthetic_fixtures_only=True,
        )
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.directory.authenticate = lambda credential: self.directory.resolve(
            {
                "synthetic-editor-credential-32-characters": "editor",
                "synthetic-reviewer-credential-32-characters": "other",
                "synthetic-publisher-credential-32-characters": "publisher",
            }.get(credential, "")
        )
        self.authority = Authority([self.receipt["public_ref"]])
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_IDENTITY_REGISTRY_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def state(self, base=None):
        return services.desk(**(base or self.common))

    def command(self, base=None):
        current = self.state(base)
        return dict(
            **(base or self.common),
            expected_snapshot=current["snapshot"],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            request_key=uuid.uuid4(),
        )

    def capture(self, base=None):
        return services.capture(**self.command(base))

    def person(self, label="شخص اصطناعي", base=None):
        return services.create_person(
            **self.command(base), label=label, reason="وصف داخلي للاختبار فقط", confirmed=True
        )

    def link(self, identity, person, base=None):
        base = base or self.common
        proposal = services.propose(
            **self.command(base),
            identity_id=identity["id"],
            person_id=person["id"],
            evidence="شهادة تحقق اصطناعية صريحة؛ لا تشابه أسماء",
            confirmed=True,
        )
        reviewer = {**base, "subject_id": "other"}
        return services.decide(
            **self.command(reviewer),
            identity_id=identity["id"],
            proposal_id=proposal["id"],
            kind="VERIFY",
            reason="تحقق بشري مستقل اصطناعي",
            confirmed=True,
        )

    def new_case(self, *, native=False, requester=None, source="youtube"):
        key = uuid.uuid4().hex
        if native:
            receipt = cases.intake_case(
                original_question="سؤال اصطناعي مستقل",
                source_event_id=key,
                requester_id=requester or "session-" + key,
                idempotency_key=key,
                synthetic_fixtures_only=True,
            )
        else:
            receipt = intake.ingest(
                raw=getattr(simulators, source)(),
                context=simulators.context(source, account="synthetic-identity-" + key),
                synthetic_fixtures_only=True,
            )
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=actor.case_keys | {receipt["public_ref"]}
            )
        self.authority.refs.add(receipt["public_ref"])
        return receipt, {**self.common, "case_id": receipt["case_id"]}
