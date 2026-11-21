"""Finite field/version grants and service-created metadata/taxonomy fixtures."""

import unittest
import uuid
from dataclasses import replace

from django.test import override_settings
from django.utils import timezone

from apps.case_organization.models import OrganizationRevision
from apps.casework.models import Case
from apps.development_taxonomy.authority import TaxonomyAuthority
from apps.development_taxonomy.models import CaseClassification, TreeVersion
from apps.development_taxonomy.test_support import TaxonomyFixture

from . import metadata
from .boundary import CLASSIFICATION_ACTIONS, METADATA_ACTIONS, digest, source_rows
from .notes_test_support import NOTE_FEATURES, NoteFixture
from .test_support import Authority, Directory

METADATA_FEATURES = {
    **NOTE_FEATURES,
    "FATWA_OPERATIONAL_METADATA_ENABLED": True,
    "FATWA_DEVELOPMENT_TAXONOMY_ENABLED": True,
}


class MetadataAuthority(Authority):
    def __init__(self, receipts):
        super().__init__(receipts)
        self.resources = set()

    def projection_epoch(self):
        return repr((super().projection_epoch(), sorted(self.resources)))

    def _allows(self, values):
        if values["resource"]["kind"] == "CASE_OPERATIONAL_SECTION":
            return super()._allows(values)
        return (
            values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and (
                values["subject_id"],
                values["role"],
                values["case_ref"],
                values["action"],
                digest(values["resource"]),
            )
            in self.resources
            and timezone.now() < self.until
        )

    def revoke(self, *, subject="operator", action=None, case_ref=None):
        super().revoke(subject=subject, action=action, case_ref=case_ref)
        self.resources = {
            row
            for row in self.resources
            if not (
                row[0] == subject
                and (action is None or row[3] == action)
                and (case_ref is None or row[2] == case_ref)
            )
        }


class ClassificationAuthority(TaxonomyAuthority):
    def __init__(self):
        self.grants, self.hook = set(), None
        self.binding_reads = set()

    def projection_epoch(self):
        return repr((sorted(self.grants), sorted(self.binding_reads)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        resource = values["resource"]
        if values["action"] == "READ" and resource.get("kind") == "BINDING":
            return (
                values["provider_id"] == Directory.provider_id
                and values["auth_epoch"] == "epoch-1"
                and (values["subject_id"], values["case_ref"]) in self.binding_reads
                and CaseClassification.objects.filter(
                    pk=resource["id"],
                    digest=resource["digest"],
                    case__public_ref=values["case_ref"],
                ).exists()
            )
        return (
            values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and (
                values["subject_id"],
                values["case_ref"],
                values["action"],
                digest(values["resource"]),
            )
            in self.grants
        )


def grant_metadata(authority, domain, target, version):
    case = Case.objects.get(pk=target["case_id"])
    tree_case = Case.objects.get(pk=version.tree.case_id)
    version_resource = metadata.resource(case, version)
    tree_resource = {"kind": "TREE", "id": str(version.tree_id), "digest": version.tree.digest}
    for subject, role in (
        ("operator", "ORGANIZER"),
        ("admin", "ORGANIZER_ADMIN"),
        ("mufti", "MUFTI"),
    ):
        authority.grants.update(
            (subject, role, case.public_ref, action, "metadata", str(case.pk))
            for action in METADATA_ACTIONS
        )
        authority.resources.update(
            (subject, role, case.public_ref, action, digest(version_resource))
            for action in CLASSIFICATION_ACTIONS
        )
        domain.grants.update(
            (subject, tree_case.public_ref, action, digest(tree_resource))
            for action in ("READ", "USE")
        )
        domain.grants.add((subject, case.public_ref, "READ", digest({"case_id": str(case.pk)})))
        domain.grants.add(
            (
                subject,
                case.public_ref,
                "BIND",
                digest(
                    {
                        "version": str(version.pk),
                        "digest": version.digest,
                    }
                ),
            )
        )
        domain.binding_reads.add((subject, case.public_ref))


class MetadataFixture(NoteFixture):
    def setUp(self):
        super().setUp()

        class Seed(TaxonomyFixture, unittest.TestCase):
            pass

        fixture = Seed()
        try:
            fixture.setUp()
            saved = fixture.review(fixture.save())
            self.version = TreeVersion.objects.select_related("tree").get(pk=saved["id"])
            self.receipts["tree"] = {key: fixture.receipt[key] for key in ("case_id", "public_ref")}
        finally:
            fixture.doCleanups()
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor,
                case_keys=frozenset([*actor.case_keys, self.receipts["tree"]["public_ref"]]),
            )
        self.authority = MetadataAuthority(self.receipts)
        self.classification_authority = ClassificationAuthority()
        grant_metadata(self.authority, self.classification_authority, self.target, self.version)
        configured = override_settings(
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY=self.classification_authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.metadata_originals = self.immutable_metadata_sources()
        self.originals = self.state()

    def immutable_metadata_sources(self):
        values = source_rows([row["case_id"] for row in self.receipts.values()])
        values.pop(OrganizationRevision._meta.db_table)
        values.pop(CaseClassification._meta.db_table)
        return digest(values)

    def metadata_values(self, **changes):
        case = Case.objects.get(pk=self.target["case_id"])
        last = OrganizationRevision.objects.filter(case=case).order_by("-version").first()
        return (
            dict(
                case_ref=case.public_ref,
                field="tags",
                values=["وسم من المنظم"],
                command_id=str(uuid.uuid4()),
                expected_metadata_version=last.version if last else 0,
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
            )
            | changes
        )

    def update_metadata(self, **changes):
        with metadata.update(**self.common, **self.metadata_values(**changes)) as result:
            return result

    def classification_values(self, **changes):
        case = Case.objects.get(pk=self.target["case_id"])
        last = CaseClassification.objects.filter(case=case).order_by("-sequence").first()
        return (
            dict(
                case_ref=case.public_ref,
                version_id=str(self.version.pk),
                version_digest=self.version.digest,
                primary=self.version.nodes[1]["id"],
                additional=[self.version.nodes[3]["id"]],
                reason="تصنيف بشري تنظيمي للقضية الاصطناعية",
                confirmed=True,
                command_id=str(uuid.uuid4()),
                expected_classification_version=last.sequence if last else 0,
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
            )
            | changes
        )

    def classify(self, **changes):
        with metadata.bind_classification(
            **self.common, **self.classification_values(**changes)
        ) as result:
            return result
