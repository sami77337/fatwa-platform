"""Fabricated documented objects; no credentials, HTTP or real account IDs."""

import json

from .adapters import SourceContext


def raw(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\r\n").encode()


def telegram(number=1, sender=100, parent=None, *, thread=None, document=False):
    message = {
        "message_id": number,
        "date": 1794902400,
        "from": {"id": sender, "is_bot": False, "first_name": "اسم تجريبي متكرر"},
        "chat": {"id": -100123, "type": "supergroup", "title": "مجموعة اصطناعية"},
        "text": "  سؤال اصطناعي محفوظ كما ورد\r\nبدون إعادة صياغة.  ",
    }
    if parent is not None:
        message["reply_to_message"] = {
            "message_id": parent,
            "date": 1794902400,
            "chat": dict(message["chat"]),
        }
    if thread is not None:
        message["message_thread_id"] = thread
    if document:
        message["caption"] = message.pop("text")
        message["document"] = {
            "file_id": "synthetic-file-1",
            "file_unique_id": "synthetic-unique-1",
            "file_name": "synthetic.txt",
            "mime_type": "text/plain",
            "file_size": 30,
        }
    return raw({"update_id": number + 1000, "message": message})


def youtube(number=1, sender="synthetic-author", parent=None):
    snippet = {
        "authorChannelId": {"value": sender},
        "authorDisplayName": "اسم تجريبي متكرر",
        "textOriginal": "سؤال اصطناعي من مورد تعليق يوتيوب",
        "textDisplay": "هذا الحقل ليس الأصل ولا يستخدمه المستورد",
        "publishedAt": "2026-11-17T00:00:00Z",
        "updatedAt": "2026-11-17T00:00:00Z",
    }
    if parent is not None:
        snippet["parentId"] = f"synthetic-comment-{parent}"
    return raw(
        {
            "kind": "youtube#comment",
            "etag": f"synthetic-etag-{number}",
            "id": f"synthetic-comment-{number}",
            "snippet": snippet,
        }
    )


def website(number=1, sender="synthetic-session", parent=None):
    data = {
        "schema": "fatwa.source-case.website.v1",
        "event_id": f"synthetic-event-{number}",
        "message_id": str(number),
        "conversation_id": "synthetic-conversation",
        "session_subject": sender,
        "display_name": "اسم تجريبي متكرر",
        "text": "سؤال اصطناعي من الموقع",
    }
    if parent is not None:
        data["reply_to"] = str(parent)
    return raw(data)


def context(source, *, account="synthetic-account", conversation="synthetic-video"):
    return SourceContext(source, account, conversation if source == "youtube" else "")
