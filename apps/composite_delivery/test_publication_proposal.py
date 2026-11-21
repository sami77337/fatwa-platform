"""A native publication proposal cannot fabricate external availability or send."""

from dataclasses import replace
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.experimental_publication.tests_ui import fields
from apps.source_case_intake import services as origins
from apps.source_case_intake import simulators
from tests.casework.test_http import post

from . import views
from .test_desk import SETTINGS, DeskFixture

FEATURES = {
    **SETTINGS,
    "FATWA_COMPOSITE_PUBLICATION_PROPOSAL_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


@override_settings(**FEATURES)
class PublicationProposalTests(DeskFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.a = origins.ingest(
            raw=simulators.youtube(),
            context=simulators.context("youtube"),
            synthetic_fixtures_only=True,
        )
        self.directory.refs = frozenset({self.a["public_ref"]})
        self.directory.projection_epoch = lambda: repr(
            (
                self.directory.provider_id,
                self.directory.refs,
                self.directory.role,
                self.directory.epoch,
            )
        )
        self.profile = replace(
            self.profile,
            capabilities=replace(self.profile.capabilities, supported=frozenset({"text", "link"})),
        )
        self.approve()

    def empty(self):
        self.assertEqual(PublicationEdition.objects.count(), 0)
        self.assertEqual(PublicationAction.objects.count(), 0)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(DeliveryIntent.objects.count(), 0)

    def test_native_explicit_proposal_hands_off_current_case_without_publishing_or_staging(self):
        page = self.open(self.login())
        self.assertContains(page, 'id="propose-publication"')
        data = {**fields(page, "composite_publication_proposal"), "confirm": "yes"}
        result = post(self.client, "/casework/staff/", data, page)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertContains(result, 'data-sendable="false"')
        self.assertContains(result, "إرسال الرابط متوقف حاليًا")
        self.assertNotContains(result, 'name="published_url"')
        self.empty()
        opened = post(self.client, "/casework/staff/", fields(result, "pub_open"), result)
        self.assertEqual(opened.status_code, 200, opened.content)
        self.assertContains(opened, self.a["public_ref"])
        self.assertContains(opened, 'value="pub_create"')
        self.empty()

    def test_arbitrary_or_local_preview_url_is_never_an_accepted_fallback_field(self):
        page = self.open(self.login())
        data = {**fields(page, "composite_publication_proposal"), "confirm": "yes"}
        for value in (
            "https://attacker.example/",
            "http://127.0.0.1/library-preview/",
            "/library-preview/",
        ):
            result = post(self.client, "/casework/staff/", {**data, "published_url": value}, page)
            self.assertEqual(result.status_code, 400)
        self.empty()

    def test_disabled_or_changed_capability_and_stale_plan_do_not_create_a_proposal(self):
        page = self.open(self.login())
        data = {**fields(page, "composite_publication_proposal"), "confirm": "yes"}
        for value in (False, 1):
            with override_settings(FATWA_COMPOSITE_PUBLICATION_PROPOSAL_ENABLED=value):
                self.assertEqual(post(self.client, "/casework/staff/", data, page).status_code, 409)
        self.profile = replace(
            self.profile,
            capabilities=replace(
                self.profile.capabilities,
                supported=frozenset({"text", "audio", "document", "link"}),
            ),
        )
        self.assertEqual(post(self.client, "/casework/staff/", data, page).status_code, 409)
        refreshed = self.open(page)
        self.assertNotContains(refreshed, 'id="propose-publication"')
        self.empty()

    def test_late_native_render_scope_revocation_discards_the_proposal(self):
        page = self.open(self.login())
        data = {**fields(page, "composite_publication_proposal"), "confirm": "yes"}
        render = views.render

        def revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            self.directory.refs = frozenset()
            return response

        with patch.object(views, "render", side_effect=revoke):
            result = post(self.client, "/casework/staff/", data, page)
        self.assertEqual(result.status_code, 409)
        self.assertNotContains(result, 'id="publication-proposal"', status_code=409)
        self.empty()
