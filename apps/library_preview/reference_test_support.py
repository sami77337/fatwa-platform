"""Real reviewed publication and explicit current FT-disclosure configuration."""

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.public_answer_media.test_support import FEATURES as MEDIA_FEATURES
from apps.public_answer_media.test_support import MediaFixture

from .fatwa_references import FatwaReferenceGrant, PublicFatwaReferences

FEATURES = {
    **MEDIA_FEATURES,
    "FATWA_REFERENCE_LOOKUP_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}


class ReferenceFixture(MediaFixture):
    def setUp(self):
        super().setUp()
        self.reference_grant = FatwaReferenceGrant(
            self.receipt["public_ref"],
            str(self.publication.pk),
            self.publication.content_sha256,
            self.directory.provider_id,
            "publisher",
            "epoch-1",
        )
        self.reference_policy = PublicFatwaReferences(
            (self.reference_grant,), timezone.now() + timedelta(minutes=20), True
        )
        configured = override_settings(FATWA_PUBLIC_FATWA_REFERENCES=self.reference_policy)
        configured.enable()
        self.addCleanup(configured.disable)
        self.reference_url = "/library-preview/by-reference/?ref=" + self.receipt["public_ref"]
        self.detail_url = f"/library-preview/editions/{self.publication.pk}/"
