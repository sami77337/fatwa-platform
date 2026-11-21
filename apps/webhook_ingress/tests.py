"""Signed synthetic callbacks and conservative Meta source projections."""

import hashlib
import hmac
from copy import deepcopy

from django.db import IntegrityError, transaction
from django.test import RequestFactory, SimpleTestCase, TransactionTestCase, override_settings

from apps.casework.models import Case
from apps.source_case_intake import http_tests as source_http
from apps.source_case_intake import services as intake
from apps.source_case_intake.adapters import SourceContext, project
from apps.source_case_intake.models import EvidenceBinding, ReviewTicket, SourceReceipt
from apps.source_case_intake.simulators import raw as encoded, telegram
from tests.casework.test_http import post
from .views import callback

ACCOUNT = "11111111-1111-4111-8111-111111111111"
URL = f"/casework/webhooks/{ACCOUNT}/"
PAGE = "synthetic-page-id"
PERSON = "synthetic-sender-id"
SECRET = "S" * 48
VERIFY = "V" * 48
QUESTION = "هل يحفظ السؤال الاصطناعي كما ورد؟\nنعم."


def profile(source):
    return {
        "source": source, "account": "synthetic-platform-account",
        "conversation": "" if source == "telegram" else PAGE,
        "secret": SECRET, "verify_token": VERIFY,
    }


def meta(source, mid="synthetic-mid-1"):
    if source in {"messenger", "instagram"}:
        return {
            "object": "page" if source == "messenger" else "instagram",
            "entry": [{
                "id": PAGE,
                "messaging": [{
                    "sender": {"id": PERSON}, "recipient": {"id": PAGE},
                    "message": {"mid": mid, "text": QUESTION},
                }],
            }],
        }
    if source == "facebook":
        return {
            "object": "page",
            "entry": [{"id": PAGE, "changes": [{
                "field": "feed", "value": {
                    "item": "comment", "verb": "add",
                    "comment_id": mid, "post_id": "synthetic-post",
                    "from": {"id": PERSON, "name": "اسم اصطناعي"},
                    "message": QUESTION,
                },
            }]}],
        }
    if source == "whatsapp":
        return {
            "object": "whatsapp_business_account",
            "entry": [{"id": PAGE, "changes": [{
                "field": "messages", "value": {
                    "metadata": {"phone_number_id": "synthetic-phone-id"},
                    "messages": [{
                        "id": mid, "from": PERSON, "type": "text",
                        "text": {"body": QUESTION},
                    }],
                },
            }]}],
        }
    raise AssertionError(source)


class MetaProjectionTests(SimpleTestCase):
    def read(self, source, payload=None):
        return project(
            encoded(meta(source) if payload is None else payload),
            SourceContext(source, "synthetic-account", PAGE),
        )

    def test_all_four_envelopes_preserve_exact_text_and_scopes(self):
        for source in ("facebook", "messenger", "instagram", "whatsapp"):
            with self.subTest(source=source):
                row = self.read(source)
                self.assertEqual(row.problem, "")
                self.assertEqual(row.original_text, QUESTION)
                self.assertEqual(row.sender, PERSON)
                self.assertEqual(row.message_id, "synthetic-mid-1")
                self.assertEqual(len(row.conversation), 64)

    def test_batch_account_mismatch_and_wrong_object_are_held(self):
        for source in ("facebook", "messenger", "instagram", "whatsapp"):
            with self.subTest(source=source):
                packet = meta(source)
                packet["entry"].append(deepcopy(packet["entry"][0]))
                self.assertEqual(self.read(source, packet).problem, "meta_batch_requires_review")
                packet = meta(source)
                packet["entry"][0]["id"] = "foreign-account"
                self.assertEqual(self.read(source, packet).problem, "invalid_or_incomplete_source")
                packet = meta(source)
                packet["object"] = "foreign-object"
                self.assertEqual(self.read(source, packet).problem, "invalid_or_incomplete_source")

    def test_echo_media_status_and_comment_edits_never_become_questions(self):
        m = meta("messenger")
        m["entry"][0]["messaging"][0]["message"]["is_echo"] = True
        self.assertEqual(self.read("messenger", m).problem, "meta_echo_requires_review")
        ig = meta("instagram")
        ig["entry"][0]["messaging"][0]["message"]["attachments"] = [{"type": "image"}]
        self.assertEqual(self.read("instagram", ig).problem, "meta_media_or_action_requires_review")
        fb = meta("facebook")
        fb["entry"][0]["changes"][0]["value"]["verb"] = "edit"
        self.assertEqual(self.read("facebook", fb).problem, "meta_nonnew_comment_requires_review")
        reply = meta("facebook")
        reply["entry"][0]["changes"][0]["value"]["parent_id"] = "synthetic-post"
        self.assertEqual(self.read("facebook", reply).problem, "meta_reply_requires_review")
        wa = meta("whatsapp")
        wa["entry"][0]["changes"][0]["value"]["statuses"] = [{"status": "read"}]
        self.assertEqual(self.read("whatsapp", wa).problem, "meta_status_or_error_requires_review")

    def test_duplicate_json_keys_fail_closed(self):
        row = project(
            b'{"object":"page","object":"instagram","entry":[]}',
            SourceContext("messenger", "synthetic-account", PAGE),
        )
        self.assertEqual(row.problem, "invalid_or_incomplete_source")
        self.assertFalse(row.original_text)

    def test_view_without_middleware_admission_cannot_accept(self):
        req = RequestFactory().post(URL, encoded(meta("messenger")), content_type="application/json")
        self.assertEqual(callback(req, account_id=ACCOUNT).status_code, 403)


@override_settings(
    FATWA_WEBHOOK_INGRESS_ENABLED=True,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    # The campaign profile deliberately keeps the whole casework web off by
    # default. Opt in explicitly for signed loopback integration fixtures only.
    FATWA_CASEWORK_WEB_ENABLED=True,
    ALLOWED_HOSTS=["127.0.0.1", "[::1]"],
)
class SignedWebhookTests(TransactionTestCase):
    def config(self, source):
        return override_settings(FATWA_WEBHOOK_INGRESS_PROFILES={ACCOUNT: profile(source)})

    def post(self, source, body=None, signature=None):
        body = encoded(meta(source)) if body is None else body
        if signature is None:
            signature = (
                SECRET if source == "telegram"
                else "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
            )
        headers = (
            {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": signature}
            if source == "telegram" else {"HTTP_X_HUB_SIGNATURE_256": signature}
        )
        with self.config(source):
            return self.client.post(
                URL, body, content_type="application/json",
                HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1", **headers,
            )

    def test_signed_messenger_raw_replay_and_separate_case_creation(self):
        raw = encoded(meta("messenger"))
        first = self.post("messenger", raw)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.post("messenger", raw).status_code, 200)
        self.assertEqual(SourceReceipt.objects.count(), 1)
        receipt = SourceReceipt.objects.get()
        self.assertEqual(bytes(receipt.raw), raw)
        self.assertEqual(receipt.problem, "")
        self.assertEqual(receipt.source, "messenger")
        self.assertEqual(Case.objects.count(), 0)
        self.assertEqual(EvidenceBinding.objects.count(), 0)
        # Only a later explicit authorized service operation binds this source.
        result = intake.process(receipt_id=receipt.pk, synthetic_fixtures_only=True)
        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(Case.objects.count(), 1)

    def test_missing_bad_or_tampered_signatures_create_nothing(self):
        self.assertEqual(self.post("messenger", signature="sha256=" + "0" * 64).status_code, 403)
        self.assertEqual(self.post("instagram", signature="").status_code, 403)
        original = encoded(meta("messenger"))
        altered = original.replace(b"synthetic-mid-1", b"synthetic-mid-2")
        old_sig = "sha256=" + hmac.new(SECRET.encode(), original, hashlib.sha256).hexdigest()
        self.assertEqual(self.post("messenger", altered, signature=old_sig).status_code, 403)
        self.assertFalse(SourceReceipt.objects.exists())

    def test_handshake_token_and_duplicate_queries_and_unknown_account(self):
        address = {"HTTP_HOST": "127.0.0.1", "REMOTE_ADDR": "127.0.0.1"}
        with self.config("messenger"):
            ok = self.client.get(
                URL, {"hub.mode": "subscribe", "hub.challenge": "932123",
                      "hub.verify_token": VERIFY}, **address
            )
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.content, b"932123")
            self.assertEqual(self.client.get(
                URL, {"hub.mode": "subscribe", "hub.challenge": "932123",
                      "hub.verify_token": "wrong"}, **address
            ).status_code, 403)
            self.assertEqual(self.client.get(
                URL + "?hub.mode=subscribe&hub.mode=subscribe&hub.challenge=1&hub.verify_token=" + VERIFY,
                **address
            ).status_code, 403)
            self.assertEqual(self.client.get(
                "/casework/webhooks/22222222-2222-4222-8222-222222222222/", **address
            ).status_code, 404)
        self.assertFalse(SourceReceipt.objects.exists())

    def test_signed_batch_is_preserved_for_review_without_case(self):
        packet = meta("instagram")
        packet["entry"].append(deepcopy(packet["entry"][0]))
        data = encoded(packet)
        result = self.post("instagram", data)
        self.assertEqual(result.status_code, 200, result.content)
        receipt = SourceReceipt.objects.get()
        self.assertEqual(bytes(receipt.raw), data)
        self.assertEqual(receipt.problem, "meta_batch_requires_review")
        result = intake.process(receipt_id=receipt.pk, synthetic_fixtures_only=True)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(ReviewTicket.objects.count(), 1)
        self.assertFalse(Case.objects.exists())

    def test_telegram_secret_header_is_checked_not_hmac(self):
        data = telegram()
        self.assertEqual(self.post("telegram", data, signature="bad").status_code, 403)
        result = self.post("telegram", data)
        self.assertEqual(result.status_code, 200, result.content)
        receipt = SourceReceipt.objects.get()
        self.assertEqual(receipt.source, "telegram")
        self.assertEqual(bytes(receipt.raw), data)
        self.assertFalse(Case.objects.exists())

    def test_facebook_and_whatsapp_capture_only(self):
        for source in ("facebook", "whatsapp"):
            with self.subTest(source=source):
                result = self.post(source)
                self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(
            set(SourceReceipt.objects.values_list("source", flat=True)),
            {"facebook", "whatsapp"},
        )
        self.assertFalse(EvidenceBinding.objects.exists())

    def test_feature_closed_and_unapproved_account_never_write(self):
        with override_settings(FATWA_WEBHOOK_INGRESS_ENABLED=False):
            self.assertNotEqual(self.post("messenger").status_code, 200)
        invalid = profile("messenger")
        invalid["account"] = "real-account-not-approved"
        body = encoded(meta("messenger"))
        sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        with override_settings(FATWA_WEBHOOK_INGRESS_PROFILES={ACCOUNT: invalid}):
            response = self.client.post(
                URL, body, content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=sig,
                HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1",
            )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(SourceReceipt.objects.exists())

    def test_sql_insert_guard_rejects_unapproved_sources_accounts_and_tampered_hashes(self):
        body = encoded(meta("messenger"))
        fields = {
            "source": "messenger",
            "account": "synthetic-platform-account",
            "event_id": "synthetic-guard-event",
            "event_key": hashlib.sha256(b"guard-event").hexdigest(),
            "message_id": "synthetic-guard-message",
            "message_key": hashlib.sha256(b"guard-message").hexdigest(),
            "conversation": "synthetic-conversation",
            "sender": PERSON,
            "requester_key": "source:synthetic-guard",
            "raw": body,
            "sha256": hashlib.sha256(body).hexdigest(),
            "attachments": [],
        }
        for change in (
            {"source": "unsupported"},
            {"account": "real-account-without-approval"},
            {"sha256": "0" * 64},
        ):
            with self.subTest(change=list(change)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    SourceReceipt.objects.create(**{**fields, **change})
        self.assertFalse(SourceReceipt.objects.exists())


@override_settings(**source_http.DESK_SETTINGS)
class MetaReviewInboxTests(TransactionTestCase):
    """End-to-end native staff filter; never a source-to-case permission grant."""

    setUp = source_http.SourceDeskHTTPTests.setUp

    def test_signed_source_receipt_only_visible_to_independent_review_scope(self):
        body = encoded(meta("messenger"))
        receipt = intake.capture(
            raw=body,
            context=SourceContext("messenger", "synthetic-platform-account", PAGE),
            synthetic_fixtures_only=True,
        )
        fields = {
            "action": "source_filter", "source": "messenger",
            "state": "pending", "page": "1",
        }
        response = post(self.client, source_http.PATH, fields, self.page)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, str(receipt.pk))
        self.assertContains(response, "Messenger")
        self.assertNotContains(response, self.held["receipt_id"])
        old_source = post(
            self.client, source_http.PATH,
            {**fields, "source": "youtube"}, self.page
        )
        self.assertNotContains(old_source, str(receipt.pk))
        self.directory.grant(self.root["public_ref"])
        withdrawn = post(
            self.client, source_http.PATH,
            {**fields, "source": "all"}, self.page
        )
        self.assertNotContains(withdrawn, str(receipt.pk))
