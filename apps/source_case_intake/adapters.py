"""Bounded offline projections of documented source objects, never API clients."""

import json
from dataclasses import dataclass, field
from hashlib import sha256

MAX_RAW = 262144
SOURCES = frozenset({"telegram", "youtube", "website", "facebook", "messenger", "instagram", "whatsapp"})


class IntakeError(ValueError):
    """Fixed safe codes only; raw source content is never an exception message."""


def digest(*parts: str) -> str:
    return sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def identifier(value: object) -> str:
    if type(value) is int:
        value = str(value)
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value != value.strip()
        or any(ord(c) < 33 or 127 <= ord(c) <= 159 for c in value)
    ):
        raise IntakeError("invalid_source_identifier")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise IntakeError("invalid_source_identifier") from exc
    return value


def text(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 16000:
        raise IntakeError("original_text_required")
    return value


@dataclass(frozen=True)
class SourceContext:
    """Server-owned simulator scope; never take account/conversation from an HTTP form.

    YouTube comment resources do not supply their video's ID. Its documented
    parent resource/query context must be supplied separately by the caller.
    """

    source: str
    account: str
    conversation: str = ""
    resource_id: str = ""  # Server-owned WhatsApp phone_number_id, never a form field.

    def validate(self):
        if self.source not in SOURCES:
            raise IntakeError("unsupported_source")
        # Explicit fixture-only namespace, not an assertion of provider authenticity.
        if not identifier(self.account).startswith("synthetic-"):
            raise IntakeError("synthetic_account_required")
        if self.source in {"youtube", "facebook", "messenger", "instagram", "whatsapp"}:
            identifier(self.conversation)
        if self.source == "whatsapp":
            if not identifier(self.resource_id).startswith("synthetic-"):
                raise IntakeError("synthetic_whatsapp_phone_scope_required")
        elif self.resource_id:
            raise IntakeError("unexpected_source_resource")


@dataclass
class Projection:
    event_id: str = ""
    message_id: str = ""
    conversation: str = ""
    thread: str = ""
    sender: str = ""
    display_name: str = ""
    parent_id: str = ""
    original_text: str = ""
    problem: str = ""
    attachments: list = field(default_factory=list)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise IntakeError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_):
    raise IntakeError("nonfinite_json")


def _json(raw):
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            item.encode("utf-8")
            if "\x00" in item:
                raise IntakeError("invalid_unicode")
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    if not isinstance(value, dict):
        raise IntakeError("object_required")
    return value


def _name(value):
    return value[:256] if isinstance(value, str) else ""


def _telegram(data, p):
    if type(data.get("update_id")) is not int:
        raise IntakeError("invalid_update_id")
    p.event_id = identifier(data["update_id"])
    edited = "edited_message" in data
    message = data["edited_message"] if edited else data["message"]
    if "message" in data and edited:
        raise IntakeError("ambiguous_update")
    p.message_id = identifier(message["message_id"])
    p.conversation = identifier(message["chat"]["id"])
    p.thread = identifier(message["message_thread_id"]) if "message_thread_id" in message else ""
    sender = message.get("from", {})
    if "sender_chat" in message or sender.get("is_bot") is not False:
        raise IntakeError("unverified_sender")
    p.sender = identifier(sender["id"])
    p.display_name = _name(sender.get("first_name"))
    if "reply_to_message" in message:
        p.parent_id = identifier(message["reply_to_message"]["message_id"])
    if "external_reply" in message:
        raise IntakeError("external_reply_requires_review")
    for kind in ("document", "audio", "voice"):
        if kind in message:
            item = message[kind]
            p.attachments.append(
                {
                    "source_file_id": identifier(item["file_id"]),
                    "filename": _name(item.get("file_name")),
                    "media_type": _name(item.get("mime_type")),
                    "kind": kind,
                }
            )
    p.original_text = text(message.get("text", message.get("caption")))
    if edited:
        p.problem = "source_edit_requires_review"
    elif any(k in message for k in ("photo", "video", "animation", "sticker", "media_group_id")):
        p.problem = "unsupported_media_requires_review"


def _youtube(data, p, context):
    if data.get("kind") != "youtube#comment":
        raise IntakeError("comment_resource_required")
    p.event_id = p.message_id = identifier(data["id"])
    p.conversation = context.conversation
    snippet = data["snippet"]
    p.sender = identifier(snippet["authorChannelId"]["value"])
    p.display_name = _name(snippet.get("authorDisplayName"))
    p.parent_id = identifier(snippet["parentId"]) if "parentId" in snippet else ""
    # textDisplay can contain HTML and transformed text; never substitute it.
    p.original_text = text(snippet.get("textOriginal"))


def _website(data, p):
    if data.get("schema") != "fatwa.source-case.website.v1":
        raise IntakeError("website_schema_required")
    p.event_id = identifier(data["event_id"])
    p.message_id = identifier(data["message_id"])
    p.conversation = identifier(data["conversation_id"])
    p.sender = identifier(data["session_subject"])
    p.display_name = _name(data.get("display_name"))
    p.parent_id = identifier(data["reply_to"]) if "reply_to" in data else ""
    p.original_text = text(data["text"])


def project(raw: bytes, context: SourceContext) -> Projection:
    context.validate()
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RAW:
        raise IntakeError("bounded_raw_bytes_required")
    p = Projection()
    try:
        data = _json(raw)
        if context.source == "telegram":
            _telegram(data, p)
        elif context.source == "youtube":
            _youtube(data, p, context)
        elif context.source == "website":
            _website(data, p)
        else:
            from .meta_projection import project_meta

            project_meta(data, p, context)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        # Original bytes still persist, even for invalid JSON/unsupported events.
        p.problem = "invalid_or_incomplete_source"
    if not p.event_id:
        p.event_id = "raw:" + sha256(raw).hexdigest()
    return p
