"""Synthetic current records; no real source text or policy grants are persisted."""

import uuid
from dataclasses import replace
from hashlib import sha256

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.library_preview.policy import PublicationGrant
from apps.public_knowledge.tests import FEATURES as PUBLIC_FEATURES
from apps.public_knowledge.tests import CurationFixture
from apps.research_library import services as library
from apps.research_library.test_support import FixtureAuthority as LibraryAuthority
from apps.research_library.test_support import payload

from . import services, sources
from .authority import CollectionAuthority

FEATURES = {
    **PUBLIC_FEATURES,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_PUBLIC_COLLECTIONS_ENABLED": True,
    "FATWA_RESEARCH_LIBRARY_ENABLED": True,
    "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED": True,
}


class FixtureAuthority(CollectionAuthority):
    def __init__(self, *refs):
        self.refs, self.denied, self.hook = set(refs), set(), None
        self.subjects = {"editor", "other", "publisher"}

    def projection_epoch(self):
        return repr((sorted(self.refs), sorted(self.denied), sorted(self.subjects)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in self.subjects
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"]
            in {"EDIT", "READ", "READ_MEMBER", "REVIEW", "APPROVE", "RELEASE", "WITHDRAW"}
            and values["kind"] in {*services.KINDS, *sources.KINDS}
            and (values["action"], values["resource_id"]) not in self.denied
        )


def identity_snapshot(directory):
    values = [
        (
            key,
            value.subject_id,
            value.role,
            value.active,
            sorted(value.case_keys),
            value.auth_epoch,
            value.valid_until.isoformat(),
            value.valid_until <= timezone.now(),
        )
        for key, value in sorted(directory.identities.items())
    ]
    return sha256(repr(values).encode()).hexdigest()


class CollectionFixture(CurationFixture):
    def setUp(self):
        super().setUp()
        self.directory.projection_epoch = lambda: identity_snapshot(self.directory)
        self.collections_authority = FixtureAuthority(self.receipt["public_ref"])
        self.library_authority = LibraryAuthority(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_PUBLIC_COLLECTIONS_AUTHORITY=self.collections_authority,
            FATWA_RESEARCH_LIBRARY_AUTHORITY=self.library_authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def staff_client(self, subject="editor"):
        client, _ = super().staff_client(subject)
        return client

    def member(self, edition=None):
        row = PublicationEdition.objects.get(pk=(edition or self.edition)["id"])
        return f"PUBLICATION|{row.pk}|{row.content_sha256}"

    def create_collection(self, **changes):
        values = dict(
            self.common,
            kind="COLLECTION",
            title="مجموعة بشرية اصطناعية",
            introduction="مقدمة محررة لا تجمع الأحكام ولا تكشف القضايا الخاصة",
            members=[self.member()],
            featured=True,
            expected_version=0,
            expected_revision=4,
            expected_evidence_version=2,
            request_key=str(uuid.uuid4()),
        )
        return services.save(**{**values, **changes})

    def collection_action(self, row, action, **changes):
        values = dict(
            self.common,
            subject_id="other" if action == "REVIEW" else "publisher",
            revision_id=row["id"],
            action=action,
            expected_actions=row["action_count"],
            expected_revision=4,
            expected_evidence_version=2,
            request_key=str(uuid.uuid4()),
            note="قرار تحريري اصطناعي مستقل",
            confirmed=True,
            minutes=15 if action == "RELEASE" else 0,
            related_id=row["lease_id"] if action == "REVOKE" else "",
        )
        return services.act(**{**values, **changes})

    def release_collection(self, row):
        for action in ("REVIEW", "APPROVE", "RELEASE"):
            row = self.collection_action(row, action)
        return row

    def collection_url(self, row):
        return f"/library-preview/collections/items/{row['public_id']}/"

    def second_publication(self):
        key = uuid.uuid4().hex
        receipt = cases.intake_case(
            original_question="PRIVATE SECOND QUESTION",
            source_event_id=key,
            requester_id="private-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        for subject, identity in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                identity, case_keys=identity.case_keys | {receipt["public_ref"]}
            )
        self.collections_authority.refs.add(receipt["public_ref"])
        self.library_authority.refs.add(receipt["public_ref"])
        common = {**self.common, "case_id": receipt["case_id"]}
        draft = cases.save_answer(
            **common, text="PRIVATE SECOND ANSWER", expected_revision=1, expected_evidence_version=1
        )
        cases.record_decision(
            **common,
            answer_id=draft["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(receipt["public_ref"])
        ):
            edition = publications.create_edition(
                **common,
                title="فتوى ثانية مصرح بها",
                category="تصنيف تجريبي",
                body="نص عام اصطناعي مستقل",
                expected_revision=3,
                expected_evidence_version=1,
            )
            publications.act(**common, edition_id=edition["id"], action="REVIEW", reviewed=True)
            publications.act(
                **{**common, "subject_id": "publisher"}, edition_id=edition["id"], action="APPROVE"
            )
        model = PublicationEdition.objects.get(pk=edition["id"])
        configured = override_settings(
            FATWA_LIBRARY_PREVIEW_POLICY=replace(
                self.preview_policy,
                publications=(
                    *self.preview_policy.publications,
                    PublicationGrant(str(model.pk), model.content_sha256),
                ),
            )
        )
        configured.enable()
        self.addCleanup(configured.disable)
        return receipt, edition

    def library_record(self, *, title="مرجع وصفي اصطناعي", raw=None):
        row = library.write_material(
            **self.common,
            namespace="collection-fixture",
            external_id=uuid.uuid4().hex,
            payload=payload(title=title),
            expected_revision=4,
            expected_evidence_version=2,
            expected_version=0,
            request_key=uuid.uuid4(),
            **(
                {"file_bytes": raw, "filename": "synthetic.txt", "media_type": "text/plain"}
                if raw
                else {}
            ),
        )
        for action in ("REVIEW", "APPROVE", "RELEASE"):
            row = library.decide(
                **{**self.common, "subject_id": "other" if action == "REVIEW" else "publisher"},
                version_id=row["version_id"],
                action=action,
                note="حقوق اصطناعية مستقلة",
                expected_actions=row["action_count"],
                expected_revision=4,
                expected_evidence_version=2,
                request_key=uuid.uuid4(),
                confirmed=True,
                uses=["PUBLIC_METADATA", "PUBLIC_CONTENT"] if action == "APPROVE" else [],
                minutes=30 if action == "APPROVE" else 15 if action == "RELEASE" else 0,
            )
        return row
