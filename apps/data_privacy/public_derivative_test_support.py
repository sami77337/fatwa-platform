"""Finite synthetic source labels and exact grants for real public readers."""

import uuid
from datetime import timedelta

from django.apps import apps
from django.test import override_settings
from django.utils import timezone

from apps.experimental_publication.models import PublicationEdition
from apps.reference.models import ReferenceHeading
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_rights import services as source_rights
from apps.source_rights.tests import Authority as SourceAuthority

from . import services
from .authority import Grant
from .catalog import TARGETS, locate
from .test_support import Authority


class PrivacyAssertions:
    def enable_privacy(self):
        # These legacy preview fixtures use an owned TOC heading. Register each
        # consumed exact source before enabling privacy; a catalog heading is
        # not itself a current grant to reuse it in a private case/public copy.
        for edition in PublicationEdition.objects.select_related("case").all():
            for citation in edition.citations:
                source = citation["source"]
                heading = ReferenceHeading.objects.get(
                    edition_id=source["edition_id"], source_row_id=source["source_row_id"]
                )
                with override_settings(
                    FATWA_SOURCE_RIGHTS_ENABLED=True,
                    FATWA_SOURCE_RIGHTS_AUTHORITY=SourceAuthority(edition.case.public_ref),
                ):
                    source_rights.register(
                        case_id=str(edition.case_id),
                        subject_id="editor",
                        provider=self.directory,
                        kind="TOC_METADATA",
                        target_id=heading.pk,
                        synthetic_fixtures_only=True,
                    )
        bind_identity_snapshot(self.directory)
        self.privacy_authority = Authority()
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.privacy_authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.before_privacy = self.originals()

    def principal(self, subject="publisher"):
        return services.staff_principal(self.directory, self.directory.resolve(subject))

    def privacy_grant(
        self,
        kind,
        identifier,
        action,
        *,
        level=None,
        public=False,
        subject="publisher",
        previous_level="",
    ):
        target = locate(kind, identifier)
        if level is None:
            level = services.current(target).level
        actor = services.public_principal() if public else self.principal(subject)
        values = dict(
            audience=actor.audience,
            provider_id=actor.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            role=actor.role,
            case_ref=target.case_ref,
            target_kind=target.kind,
            target_id=target.identifier,
            source_digest=target.source_digest,
            classification=level,
            previous_level=previous_level,
            action=action,
        )
        key = Authority.key(values)
        self.privacy_authority.grants[key] = Grant(timezone.now() + timedelta(minutes=10))
        return key

    def label(self, kind, identifier, level):
        target = locate(kind, identifier)
        rows = services.history(target)
        self.privacy_grant(
            kind,
            identifier,
            "CLASSIFY",
            level=level,
            previous_level=rows[-1].level if rows else "",
        )
        return services.classify(
            kind=kind,
            identifier=identifier,
            level=level,
            note="تصنيف اصطناعي مستقل؛ الأصل الخاص لا يرث إتاحة المشتق",
            expected_digest=rows[-1].digest if rows else services.ZERO,
            expected_source_digest=target.source_digest,
            request_key=uuid.uuid4(),
            provider=self.directory,
            subject_id="publisher",
            synthetic_fixtures_only=True,
        )

    def admit_known(self, *, exclude=()):
        """Enumerate this fixture's exact versions; never an authority wildcard."""
        public = {
            "PUBLICATION",
            "PUBLIC_KNOWLEDGE",
            "PUBLIC_COLLECTION",
            "PUBLIC_TEACHING",
            "PUBLIC_MEDIA",
            "LIBRARY_VERSION",
        }
        private = {
            "CASE",
            "ANSWER",
            "ANSWER_PART",
            "RECORDING_TRANSCRIPT",
            "LESSON_VERSION",
            "SERIES_VERSION",
            "KNOWLEDGE_REVISION",
            "SOURCE_VERSION",
        }
        excluded = {(kind, str(identifier)) for kind, identifier in exclude}
        self.exact_grants = {}
        for kind in sorted(public | private):
            model = apps.get_model(TARGETS[kind][0])
            for identifier in model.objects.order_by("pk").values_list("pk", flat=True):
                if (kind, str(identifier)) in excluded:
                    continue
                self.label(kind, identifier, "PUBLIC" if kind in public else "CONFIDENTIAL")
                if kind in public:
                    self.exact_grants[(kind, str(identifier), "READ")] = self.privacy_grant(
                        kind, identifier, "READ", public=True
                    )
                if kind == "PUBLICATION":
                    self.privacy_grant(kind, identifier, "SEARCH", public=True)
                if kind != "CASE":
                    self.exact_grants[(kind, str(identifier), "PUBLISH")] = self.privacy_grant(
                        kind, identifier, "PUBLISH"
                    )

    def revoke(self, kind, identifier, action):
        key = self.exact_grants[(kind, str(identifier), action)]
        return self.privacy_authority.grants.pop(key)

    def originals(self):
        labels = (
            "casework.Case",
            "casework.CaseEvent",
            "casework.AnswerRevision",
            "casework.CaseDecision",
            "experimental_publication.PublicationEdition",
            "experimental_publication.PublicationAction",
            "public_knowledge.PublicRevision",
            "public_knowledge.PublicAction",
            "public_collections.CollectionRevision",
            "public_collections.CollectionAction",
            "public_teaching.TeachingVersion",
            "public_teaching.TeachingAction",
            "public_answer_media.PublicMediaEdition",
            "public_answer_media.PublicMediaAction",
            "public_answer_media.RecordingTranscript",
            "public_answer_media.TranscriptAction",
            "source_rights.SourceVersion",
            "source_rights.SourceRegistration",
            "source_rights.RightsRevision",
            "source_rights.RightsAction",
            "scholarly_links.LessonVersion",
            "scholarly_links.SeriesVersion",
            "scholarly_links.CaseRelation",
        )
        return {
            label: list(apps.get_model(label).objects.order_by("pk").values()) for label in labels
        }

    def assert_originals(self):
        self.assertEqual(self.originals(), self.before_privacy)

    def assert_private_case(self, identifier):
        target = locate("CASE", identifier)
        self.assertEqual(services.current(target).level, "CONFIDENTIAL")
        with self.assertRaises(services.PrivacyDenied):
            services.require("CASE", identifier, principal=services.public_principal())
