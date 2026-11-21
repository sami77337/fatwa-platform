"""Current exact-publication tool grants on synthetic approved source fixtures."""

from dataclasses import replace
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.public_answer_media.test_support import FEATURES as MEDIA_FEATURES
from apps.public_answer_media.test_support import MediaFixture

from .authority import ReaderGrant, ReaderToolsAuthority
from .services import ACTIONS

FEATURES = {**MEDIA_FEATURES, "FATWA_PUBLIC_READER_TOOLS_ENABLED": True}


class FixtureAuthority(ReaderToolsAuthority):
    def __init__(self, publication, provider_id):
        deadline = timezone.now() + timedelta(minutes=20)
        self.grants = {
            action: ReaderGrant(
                str(publication.pk),
                publication.content_sha256,
                action,
                provider_id,
                "publisher",
                "epoch-1",
                deadline,
            )
            for action in ACTIONS
        }
        self.hook = None

    def projection_epoch(self):
        return repr(sorted(self.grants.items()))

    def grant(self, **values):
        if self.hook:
            self.hook(values)
        granted = self.grants.get(values["action"])
        if granted is None or (
            granted.publication_id != values["publication_id"]
            or granted.content_sha256 != values["content_sha256"]
        ):
            return None
        return granted

    def change(self, action, **values):
        self.grants[action] = replace(self.grants[action], **values)


class ReaderFixture(MediaFixture):
    def setUp(self):
        super().setUp()
        self.reader_authority = FixtureAuthority(self.publication, self.directory.provider_id)
        configured = override_settings(FATWA_PUBLIC_READER_TOOLS_AUTHORITY=self.reader_authority)
        configured.enable()
        self.addCleanup(configured.disable)
