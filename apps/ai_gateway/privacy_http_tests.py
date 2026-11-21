"""Native classified-source composition: real guard, provider gap and fresh auth."""

from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.casework.models import AnswerRevision
from apps.data_privacy import services as privacy_services
from apps.data_privacy.services import PrivacyDenied
from apps.staff_sessions import test_support as session_support
from apps.staff_sessions.models import FreshProof, SessionRevocation
from config.settings import campaign_review
from tests.casework.test_http import hidden

from . import identity, test_http
from .models import CandidateBatch, GatewayOutcome
from .privacy_test_support import ClassifiedSources
from .test_support import FEATURES, GatewayFixture

MIDDLEWARE = list(
    dict.fromkeys(
        [
            *campaign_review.MIDDLEWARE[:2],
            "apps.data_privacy.integration.PrivacyResponses",
            *campaign_review.MIDDLEWARE[2:],
        ]
    )
)


@override_settings(**{**FEATURES, "MIDDLEWARE": MIDDLEWARE})
class CitationPrivacyHTTPTests(GatewayFixture, TransactionTestCase):
    login = test_http.NativeFixture.login
    ai_post = test_http.NativeFixture.ai_post

    def setUp(self):
        super().setUp()
        self.privacy = ClassifiedSources(self, self.directory, "editor")
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH", "AI"))
        self.privacy.classify(
            "LIBRARY_VERSION", self.material["version_id"], actions=("READ", "SEARCH", "AI")
        )

    def test_real_campaign_guard_session_and_classified_source_support_provider_and_handoff(self):
        client, opened = self.login()
        actor, wrapped = identity.principal(opened.wsgi_request)
        principal = privacy_services.staff_principal(wrapped, actor)
        self.assertIs(principal.provider, wrapped)

        class UnregisteredWrapper(identity.SessionDirectory):
            pass

        forged = object.__new__(UnregisteredWrapper)
        forged.__dict__.update(wrapped.__dict__)
        with self.assertRaises(PrivacyDenied):
            privacy_services.staff_principal(forged, actor)
        outside = []
        self.ai_provider.hook = lambda: outside.append(connection.in_atomic_block)
        csrf = hidden(opened, "csrfmiddlewaretoken")
        result = self.ai_post(client, csrf, test_http.initial_state(opened))
        self.assertContains(result, 'data-run-status="SUCCEEDED"')
        self.assertEqual(outside, [False])
        original = self.ai_post(client, csrf, test_http.states(result)[0], "open")
        self.assertContains(original, "<mark>مصدر اصطناعي</mark>")
        selected = self.ai_post(client, csrf, test_http.states(original)[1], "select")
        self.assertContains(selected, 'data-ai-handoff="1"')
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_privacy_withdrawal_inside_provider_removes_native_response_and_batch(self):
        client, opened = self.login()
        key = self.privacy.allow("LIBRARY_VERSION", self.material["version_id"], "AI")
        self.ai_provider.hook = lambda: self.privacy.authority.grants.pop(key)
        result = self.ai_post(
            client, hidden(opened, "csrfmiddlewaretoken"), test_http.initial_state(opened)
        )
        self.assertEqual(result.status_code, 404, result.content)
        self.assertNotContains(result, self.source_text, status_code=404)
        self.assertNotContains(result, 'data-ai-handoff="1"', status_code=404)
        self.assertEqual(len(self.ai_provider.calls), 1)
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(GatewayOutcome.objects.get().status, "REVOKED")


@override_settings(
    **{
        **session_support.FEATURES,
        "ROOT_URLCONF": "config.campaign_urls",
        "MIDDLEWARE": MIDDLEWARE,
    }
)
class PrivacyFreshAuthHTTPTests(session_support.SessionFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.privacy = ClassifiedSources(self, self.directory, "mufti")
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))
        self.privacy.classify("ANSWER", AnswerRevision.objects.get().pk, actions=("READ",))

    def test_real_middleware_classified_case_and_fresh_auth_use_short_transactions(self):
        self.assertEqual(self.client.get("/casework/staff/").status_code, 200)
        outside = []
        self.directory.hook = lambda: outside.append(connection.in_atomic_block)
        page = self.fresh()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(outside, [False])
        self.assertEqual(FreshProof.objects.count(), 1)
        self.assertEqual(self.revoke(page).status_code, 303)
        self.assertEqual(SessionRevocation.objects.count(), 1)
        self.assertEqual(self.other_client.get("/casework/staff/").status_code, 403)
        self.assertEqual(self.client.get("/casework/staff/").status_code, 200)
