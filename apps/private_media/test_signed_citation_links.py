"""Temporary current-session locators on citation originals and PDF derivatives."""

import io
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import RequestFactory, SimpleTestCase, TransactionTestCase, override_settings
from pypdf import PdfReader

from apps.pdf_citations import tests as pdf_fixture
from apps.precise_citations import test_http as precise_http
from apps.precise_citations.test_support import FEATURES as PRECISE_FEATURES
from apps.precise_citations.test_support import CitationFixture
from apps.timed_citations import tests as timed_fixture
from tests.casework.test_http import WEB_SETTINGS, post

from . import links
from .test_signed_links import LINK_SETTINGS, LinkAssertions, client


def features(base):
    return {
        **base,
        **LINK_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "MIDDLEWARE": [
            "apps.private_media.links.PrivateMediaResponses",
            *WEB_SETTINGS["MIDDLEWARE"],
        ],
    }


class NativeCitationEntry:
    def setUp(self):
        super().setUp()
        self.directory.projection_epoch = lambda: repr(sorted(self.directory.identities.items()))
        self.client = client()
        page = self.client.get("/casework/staff/login/")
        login = post(
            self.client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        self.assertEqual(login.status_code, 303, login.content)

    def open_native(self, action, record):
        page = self.client.get("/casework/staff/")
        return post(
            self.client,
            "/casework/staff/",
            {"action": action, "case_ref": self.receipt["public_ref"], "citation_id": record["id"]},
            page,
        )


@override_settings(**features(timed_fixture.SETTINGS))
class SignedTimedCitationTests(
    LinkAssertions, NativeCitationEntry, timed_fixture.Fixture, TransactionTestCase
):
    def test_review_and_confirmed_audio_use_exact_current_tickets_and_current_rights(self):
        record = self.propose(start_ms=10, end_ms=90)
        review_path = f"/casework/staff/timed-citations/{record['id']}/review-audio/"
        review = self.signed_url(self.open_native("timed_preview", record), review_path)
        self.assertEqual(urlsplit(review).fragment, "t=0.01,0.09")
        self.exact_range(self.client, review, self.audio["raw"])
        self.confirm(record)
        path = f"/casework/staff/timed-citations/{record['id']}/audio/"
        url = self.signed_url(self.open_native("timed_open", record), path)
        self.denied_file(self.client.get(path), self.audio["raw"])
        self.exact_range(self.client, url, self.audio["raw"])
        self.denied_file(
            self.client.get(review.replace("review-audio/", "audio/")), self.audio["raw"]
        )
        self.rights.actions.remove("READ_MEDIA")
        for method in (self.client.get, self.client.head):
            self.denied_file(method(url, HTTP_RANGE="bytes=0-10"), self.audio["raw"])

    def test_late_citation_withdrawal_discards_already_built_audio_range(self):
        record = self.propose()
        self.confirm(record)
        path = f"/casework/staff/timed-citations/{record['id']}/audio/"
        url = self.signed_url(self.open_native("timed_open", record), path)
        build = links._range_response

        def withdraw(*args, **kwargs):
            response = build(*args, **kwargs)
            timed_fixture.services.act(
                **self.common, citation_id=record["id"], action="WITHDRAW", confirmed=True
            )
            return response

        with patch.object(links, "_range_response", side_effect=withdraw):
            self.denied_file(self.client.get(url, HTTP_RANGE="bytes=0-10"), self.audio["raw"])


@override_settings(**features(pdf_fixture.SETTINGS))
class SignedPdfCitationTests(
    LinkAssertions, NativeCitationEntry, pdf_fixture.Fixture, TransactionTestCase
):
    def test_original_and_exact_selected_page_keep_distinct_tickets_and_current_rights(self):
        record = self.propose()
        review = self.open_native("pdf_preview", record)
        prefix = f"/casework/staff/pdf-citations/{record['id']}/"
        full = self.signed_url(review, prefix + "review-document/")
        selected = self.signed_url(review, prefix + "review-page/")
        self.assertEqual(urlsplit(full).fragment, "page=2")
        self.exact_range(self.client, full, self.pdf["raw"])
        selected_raw = self.client.get(selected).content
        self.assertEqual(len(PdfReader(io.BytesIO(selected_raw)).pages), 1)
        self.assertNotEqual(selected_raw, self.pdf["raw"])
        self.exact_range(self.client, selected, selected_raw)
        self.denied_file(
            self.client.get(selected.replace("review-page/", "review-document/")), self.pdf["raw"]
        )
        self.confirm(record)
        page = self.open_native("pdf_open", record)
        full = self.signed_url(page, prefix + "document/")
        selected = self.signed_url(page, prefix + "page/")
        self.exact_range(self.client, full, self.pdf["raw"])
        self.exact_range(self.client, selected, selected_raw)
        self.denied_file(self.client.head(prefix + "document/"), self.pdf["raw"])
        self.rights.actions.remove("READ_MEDIA")
        for url, raw in ((full, self.pdf["raw"]), (selected, selected_raw)):
            self.denied_file(self.client.get(url, HTTP_RANGE="bytes=0-10"), raw)
            self.denied_file(self.client.head(url), raw)


@override_settings(**features(PRECISE_FEATURES))
class SignedPreciseCitationTests(LinkAssertions, CitationFixture, TransactionTestCase):
    login = precise_http.CitationHTTPTests.login

    def test_citation_source_ticket_keeps_source_and_reader_grants_independent(self):
        record = self.save_citations()
        browser, _ = self.login()
        path = f"/casework/precise-citations/sources/{record['entries'][0]['id']}/"
        url = self.signed_url(browser.get(path), path + "file/")
        raw = "مصدر اصطناعي دقيق محفوظ للإحالة".encode()
        self.denied_file(browser.get(path + "file/"), raw)
        self.exact_range(browser, url, raw)
        other, _ = self.login()
        self.denied_file(other.get(url, HTTP_RANGE="bytes=0-10"), raw)
        self.citation_authority.denied.add("READ_SOURCE")
        self.denied_file(browser.get(url, HTTP_RANGE="bytes=0-10"), raw)
        self.denied_file(browser.head(url), raw)

    def test_late_citation_source_denial_after_range_build_discards_complete_response(self):
        record = self.save_citations()
        browser, _ = self.login()
        path = f"/casework/precise-citations/sources/{record['entries'][0]['id']}/"
        url = self.signed_url(browser.get(path), path + "file/")
        build = links._range_response

        def revoke(*args, **kwargs):
            response = build(*args, **kwargs)
            self.citation_authority.denied.add("READ_SOURCE")
            return response

        with patch.object(links, "_range_response", side_effect=revoke):
            self.denied_file(
                browser.get(url, HTTP_RANGE="bytes=0-10"),
                "مصدر اصطناعي دقيق محفوظ للإحالة".encode(),
            )


@override_settings(**LINK_SETTINGS)
class SignedQueryAdmissionTests(SimpleTestCase):
    def test_only_canonical_query_on_closed_byte_route_is_admitted_without_mutation(self):
        factory = RequestFactory()
        path = "/casework/status/attachments/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/"
        value = "a" * 60
        request = factory.get(path, {"access": value})
        raw = request.META["QUERY_STRING"]
        self.assertTrue(links.admits_query(request))
        self.assertEqual(request.META["QUERY_STRING"], raw)
        self.assertEqual(request.GET["access"], value)
        request.META["QUERY_STRING"] = "access=" + "b" * 60
        self.assertFalse(links.admits_query(request))
        for url in ("/casework/staff/", "/library-preview/", path + "extra/"):
            self.assertFalse(links.admits_query(factory.get(url, {"access": value})))
        for query in (
            "access=" + value + "&access=" + value,
            "access=" + value + "&purpose=DOWNLOAD",
            "access=" + "%61" * 60,
            "access=" + "a" * 1801,
        ):
            request = factory.get(path + "?" + query)
            self.assertFalse(links.admits_query(request))
            self.assertEqual(request.META["QUERY_STRING"], query)
