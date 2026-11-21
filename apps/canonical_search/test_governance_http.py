"""Campaign CSRF forms, independent human review and response-time revocation."""

import re
import uuid
from html import unescape
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.casework.models import CaseEvent, CaseSource
from tests.casework.test_http import post

from . import governance_views
from .governance_test_support import CREDENTIALS, FEATURES, TERM, GovernanceFixture
from .models import ShadowComparison, SynonymDecision, SynonymPreview, SynonymRevision


def form_state(page, action, number=0):
    forms = [
        form
        for form in re.findall(r"<form\b.*?</form>", page.content.decode(), re.S)
        if f'name="action" value="{action}"' in form
    ]
    return unescape(re.search(r'name="state" value="([^"]+)"', forms[number])[1])


def entry_fields():
    result = {key: "" for key in governance_views.ENTRY_FIELDS | governance_views.MAPPING_FIELDS}
    result.update(entry_0_key="synthetic-one", entry_0_term=TERM, entry_0_alternatives="المعاملات")
    return result


@override_settings(**FEATURES)
class SearchGovernanceHTTPTests(GovernanceFixture, TransactionTestCase):
    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = post(
            client, "/casework/staff/login/", {"credential": CREDENTIALS[subject]}, page
        )
        self.assertEqual(response.status_code, 303, response.content)
        return client, client.get("/casework/staff/")

    def submit(self, client, response, action, **fields):
        return post(
            client,
            "/casework/staff/",
            {"action": action, "case_ref": self.receipt["public_ref"], **fields},
            response,
        )

    def open(self, subject="editor"):
        client, page = self.login(subject)
        response = self.submit(client, page, "cs_dictionary_open")
        self.assertEqual(response.status_code, 200, response.content)
        return client, response

    def save(self, client, page, **changes):
        fields = {
            "state": form_state(page, "cs_dictionary_save"),
            "title": "قاموس تجريبي يحرره المستخدم",
            "provenance": "مصدر اصطناعي لا يتضمن اعتماد ألفاظ شرعية",
            **entry_fields(),
        }
        return self.submit(client, page, "cs_dictionary_save", **{**fields, **changes})

    def test_native_bounded_dictionary_preview_independent_review_search_and_shadow(self):
        before = CaseEvent.objects.count()
        client, page = self.open()
        page = self.save(client, page)
        self.assertEqual(page.status_code, 200, page.content)
        page = self.submit(
            client,
            page,
            "cs_dictionary_preview",
            state=form_state(page, "cs_dictionary_preview"),
            queries=TERM,
        )
        self.assertContains(page, 'class="preview-baseline-count">0')
        self.assertContains(page, 'class="preview-candidate-count">2')
        self_review = self.submit(
            client,
            page,
            "cs_dictionary_review",
            state=form_state(page, "cs_dictionary_review"),
            decision="APPROVE",
            note="مراجعة غير مستقلة مرفوضة",
            ttl="60",
            confirm="yes",
        )
        self.assertEqual(self_review.status_code, 409)
        reviewer, review_page = self.open("other")
        reviewed = self.submit(
            reviewer,
            review_page,
            "cs_dictionary_review",
            state=form_state(review_page, "cs_dictionary_review"),
            decision="APPROVE",
            note="اطلعت على المصدر والمعاينة واستقلال المراجعة",
            ttl="60",
            confirm="yes",
        )
        self.assertContains(reviewed, 'data-state="APPROVE"')
        page = self.submit(client, page, "cs_dictionary_open")
        page = self.submit(
            client,
            page,
            "cs_dictionary_search",
            state=form_state(page, "cs_dictionary_search"),
            query=TERM,
            page="1",
        )
        self.assertContains(page, 'id="dictionary-result-count">2 نتيجة')
        self.assertContains(page, "المراجع <bdi>other</bdi>")
        observed = self.submit(
            client, page, "cs_shadow_run", state=form_state(page, "cs_shadow_run"), query=TERM
        )
        self.assertContains(observed, 'id="shadow-baseline-count">0')
        self.assertContains(observed, 'id="shadow-candidate-count">2')
        self.assertIn("no-store", observed["Cache-Control"])
        self.assertEqual(ShadowComparison.objects.count(), 1)
        self.assertEqual(CaseSource.objects.get().original_question, self.question)
        self.assertEqual(CaseEvent.objects.count(), before)

    def test_form_binding_csrf_extra_fields_disabled_feature_and_current_action_denial(self):
        client, page = self.open()
        no_csrf = client.post(
            "/casework/staff/",
            {"action": "cs_dictionary_open", "case_ref": self.receipt["public_ref"]},
        )
        self.assertEqual(no_csrf.status_code, 403)
        extra = self.save(client, page, production="yes")
        self.assertEqual(extra.status_code, 400)
        other, other_page = self.open()
        stale = self.submit(
            other,
            other_page,
            "cs_dictionary_save",
            state=form_state(page, "cs_dictionary_save"),
            title="قاموس",
            provenance="مصدر",
            **entry_fields(),
        )
        self.assertEqual(stale.status_code, 400)
        self.authority.denied.add("DICTIONARY_EDIT")
        denied = self.save(client, page)
        self.assertEqual(denied.status_code, 409)
        readable = self.submit(client, page, "cs_dictionary_open")
        self.assertEqual(readable.status_code, 200, readable.content)
        self.assertNotContains(readable, 'id="dictionary-save-form"')
        with override_settings(FATWA_SEARCH_GOVERNANCE_ENABLED=False):
            self.assertEqual(self.submit(client, page, "cs_dictionary_open").status_code, 409)
        self.assertFalse(SynonymRevision.objects.exists())

    def test_save_and_shadow_roll_back_if_final_render_loses_current_authority(self):
        client, page = self.open()
        original = governance_views.render

        def revoke_after_render(*args, **kwargs):
            response = original(*args, **kwargs)
            self.authority.denied.add("DICTIONARY_READ")
            return response

        with patch.object(governance_views, "render", side_effect=revoke_after_render):
            denied = self.save(client, page)
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(SynonymRevision.objects.exists())
        self.authority.denied.clear()
        self.approved()
        page = self.submit(client, page, "cs_dictionary_open")
        with patch.object(governance_views, "render", side_effect=revoke_after_render):
            denied = self.submit(
                client, page, "cs_shadow_run", state=form_state(page, "cs_shadow_run"), query=TERM
            )
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(ShadowComparison.objects.exists())

    def test_revision_mapping_retirement_and_stale_comparison_are_native(self):
        first, _ = self.approved()
        client, page = self.open()
        observed = self.submit(
            client, page, "cs_shadow_run", state=form_state(page, "cs_shadow_run"), query=TERM
        )
        comparison_state = form_state(observed, "cs_shadow_read")
        mapped = self.save(
            client,
            observed,
            entry_0_key="synthetic-renamed",
            entry_0_term="بديلمصطنع",
            entry_0_alternatives="الزكاة",
            map_0_kind="RENAMED",
            map_0_targets="synthetic-renamed",
            map_0_reason="تسمية اختبارية مختلفة موثقة",
        )
        self.assertContains(mapped, 'data-number="2"')
        self.assertEqual(SynonymRevision.objects.get(number=1).pk, uuid.UUID(first["id"]))
        self.assertEqual(SynonymPreview.objects.count(), 1)
        retired = self.submit(
            client,
            mapped,
            "cs_dictionary_review",
            state=form_state(mapped, "cs_dictionary_review"),
            decision="RETIRE",
            note="سحب الإصدار الأول بعد مقارنة أثره",
            ttl="0",
            confirm="yes",
        )
        self.assertContains(retired, 'data-state="RETIRE"')
        denied = self.submit(client, retired, "cs_shadow_read", state=comparison_state)
        self.assertEqual(denied.status_code, 409)
        self.assertNotContains(retired, 'id="shadow-history"')
        self.assertEqual(SynonymDecision.objects.count(), 2)
