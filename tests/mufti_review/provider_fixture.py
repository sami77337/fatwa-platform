"""Explicit test-only directory; never registered by application defaults."""
from datetime import timedelta
from django.utils import timezone
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider
from apps.fast9_case_source_join.answer_drafts import CASE_KEY


class FixtureDirectory(MuftiIdentityProvider):
    provider_id = 'test-directory'

    def __init__(self, token='M' * 64):
        self.token = token
        self.current = MuftiIdentity('mufti-fixture', 'MUFTI', True, frozenset({CASE_KEY}),
            'epoch-1', timezone.now() + timedelta(minutes=10))
        self.unavailable = False

    def authenticate(self, credential):
        if credential != self.token:
            raise ValueError('invalid_test_credential')
        return self.resolve('mufti-fixture')

    def resolve(self, subject_id):
        if self.unavailable:
            raise OSError('directory_unavailable')
        return self.current if subject_id == self.current.subject_id else None
