"""Explicit finite synthetic policy for human work; no production policy default."""

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.casework.models import AnswerRevision

from .authority import UnclassifiedWorkGrant
from .campaign_test_support import CampaignFixture
from .catalog import digest, locate
from .test_support import Authority


class WorkAuthority(Authority):
    def __init__(self):
        super().__init__()
        self.work = set()
        self.creators = set()
        self.until = timezone.now() + timedelta(minutes=10)

    def projection_epoch(self):
        return digest(
            [
                super().projection_epoch(),
                sorted(self.work),
                sorted(self.creators),
                self.until.isoformat(),
            ]
        )

    def authorize_unclassified_work(self, **values):
        pin = tuple(
            values[key]
            for key in (
                "target_kind",
                "target_id",
                "source_digest",
                "provider_id",
                "subject_id",
                "auth_epoch",
                "role",
                "case_ref",
            )
        )
        allowed = pin in self.work
        if values["target_kind"] == "ANSWER":
            answer = AnswerRevision.objects.filter(pk=values["target_id"]).first()
            if answer is not None:
                creator = (
                    str(answer.case_id),
                    answer.provider_id,
                    answer.subject_id,
                    answer.auth_epoch,
                )
                allowed |= (
                    creator in self.creators
                    and creator[1:]
                    == (values["provider_id"], values["subject_id"], values["auth_epoch"])
                    and locate("ANSWER", answer.pk).source_digest == values["source_digest"]
                )
        if allowed:
            return UnclassifiedWorkGrant(self.until, digest(values))
        return None


class WorkFixture(CampaignFixture):
    def setUp(self):
        super().setUp()
        original = self.authority
        self.authority = WorkAuthority()
        self.authority.grants = original.grants.copy()
        self.enterContext(override_settings(FATWA_DATA_PRIVACY_AUTHORITY=self.authority))
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def permit_private_work(self):
        actor = self.directory.resolve("mufti")
        self.authority.work.add(
            (
                "CASE",
                self.target.identifier,
                self.target.source_digest,
                self.directory.provider_id,
                actor.subject_id,
                actor.auth_epoch,
                actor.role,
                self.target.case_ref,
            )
        )
        # This synthetic policy explicitly permits only the current actor's new
        # immutable answer revisions in this one case, under existing Mufti gates.
        self.authority.creators.add(
            (
                self.target.case_id,
                self.directory.provider_id,
                actor.subject_id,
                actor.auth_epoch,
            )
        )
