"""Finite organizer publication grants over a Mufti-prepared immutable edition."""

from django.test import override_settings
from django.utils import timezone

from apps.experimental_publication import services as editorial
from apps.experimental_publication.authority import PublicationAuthority as DomainAuthority
from apps.experimental_publication.models import PublicationAction, PublicationEdition

from . import publication
from .boundary import digest, source_rows
from .test_support import FEATURES, Authority, Directory
from .transcript_test_support import TranscriptFixture

PUBLICATION_FEATURES = {
    **FEATURES,
    "FATWA_OPERATIONAL_PUBLICATION_ENABLED": True,
    "FATWA_LIBRARY_PREVIEW_ENABLED": True,
}


class PublicationGrants(Authority):
    def __init__(self, receipts):
        super().__init__(receipts)
        self.publication_rules = set()

    def projection_epoch(self):
        return repr((super().projection_epoch(), sorted(self.publication_rules)))

    def _allows(self, values):
        r = values["resource"]
        if r["kind"] == "CASE_OPERATIONAL_SECTION":
            return super()._allows(values)
        return (
            r["kind"] == "CASE_PUBLICATION_EDITION"
            and values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and timezone.now() < self.until
            and (
                values["subject_id"],
                values["role"],
                values["case_ref"],
                values["action"],
                r["edition_id"],
                r["content_sha256"],
            )
            in self.publication_rules
            and PublicationEdition.objects.filter(
                pk=r["edition_id"],
                content_sha256=r["content_sha256"],
                case_id=r["case_id"],
                case__public_ref=values["case_ref"],
                answer_id=r["answer_id"],
                decision_id=r["decision_id"],
                evidence_version=r["evidence_version"],
            ).exists()
        )

    def revoke(self, *, subject="operator", action=None, case_ref=None):
        super().revoke(subject=subject, action=action, case_ref=case_ref)
        self.publication_rules = {
            row
            for row in self.publication_rules
            if not (
                row[0] == subject
                and (action is None or row[3] == action)
                and (case_ref is None or row[2] == case_ref)
            )
        }


class PublicationDomainAuthority(DomainAuthority):
    def __init__(self):
        self.rules, self.denied, self.hook = set(), set(), None

    def projection_epoch(self):
        return digest((sorted(self.rules), sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and (values["subject_id"], values["case_ref"], values["action"]) in self.rules
            and (values["subject_id"], values["action"]) not in self.denied
        )


def grant_publication(authority, domain, receipt, editions):
    for subject, role in (
        ("operator", "ORGANIZER"),
        ("admin", "ORGANIZER_ADMIN"),
        ("mufti", "MUFTI"),
    ):
        authority.grants.add(
            (
                subject,
                role,
                receipt["public_ref"],
                "READ_PUBLICATION_MANAGER",
                "publication_manager",
                receipt["case_id"],
            )
        )
        for action, operation in publication.ACTION_MAP.items():
            domain.rules.add((subject, receipt["public_ref"], action))
            for edition in editions:
                authority.publication_rules.add(
                    (
                        subject,
                        role,
                        receipt["public_ref"],
                        operation,
                        str(edition.pk),
                        edition.content_sha256,
                    )
                )


class PublicationFixture(TranscriptFixture):
    def setUp(self):
        super().setUp()
        self.authority, self.publication_domain = (
            PublicationGrants(self.receipts),
            PublicationDomainAuthority(),
        )
        configured = override_settings(
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=self.publication_domain,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        row = editorial.create_edition(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            title="نسخة للنشر جهزها المفتي",
            category="موضوع اصطناعي",
            body="نسخة تحريرية اصطناعية جاهزة لمراجعة الخصوصية والنشر.",
            expected_revision=3,
            expected_evidence_version=1,
            synthetic_fixtures_only=True,
        )
        self.edition = PublicationEdition.objects.get(pk=row["id"])
        grant_publication(self.authority, self.publication_domain, self.target, [self.edition])
        self.originals, self.publication_originals = (
            self.state(),
            self.immutable_publication_sources(),
        )

    def immutable_publication_sources(self):
        values = source_rows([row["case_id"] for row in self.receipts.values()])
        values.pop(PublicationAction._meta.db_table)
        return digest(values)

    def decision_values(self, *, edition=None, **changes):
        edition = edition or self.edition
        return {
            "case_ref": self.target["public_ref"],
            "edition_id": str(edition.pk),
            "content_sha256": edition.content_sha256,
            "action": "REVIEW",
            "confirmed": True,
            "expected_actions": edition.actions.count(),
            "expected_revision": 3,
            "expected_evidence_version": 1,
            **changes,
        }

    def publication_decide(self, *, subject="operator", **changes):
        with publication.decide(
            **{**self.common, "subject_id": subject}, **self.decision_values(**changes)
        ) as result:
            return result
