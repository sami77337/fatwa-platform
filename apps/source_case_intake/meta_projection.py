"""Strict single-event projections from documented Meta webhook envelopes.

Only explicitly scoped, synthetic-account fixtures are supported by the existing
source intake authority. A signed webhook is *transport* evidence, not sender
identity verification, human authorization or a right to publish. Unsupported
batches/updates retain original bytes under a review reason.
"""

from .adapters import IntakeError, digest, identifier, text

OBJECTS = {
    "facebook": "page",
    "messenger": "page",
    "instagram": "instagram",
    "whatsapp": "whatsapp_business_account",
}


def _entry(data, context, projection):
    if data.get("object") != OBJECTS[context.source]:
        raise IntakeError("meta_object_scope_mismatch")
    rows = data.get("entry")
    if type(rows) is not list or len(rows) != 1:
        projection.problem = "meta_batch_requires_review"
        return None
    row = rows[0]
    if type(row) is not dict:
        raise IntakeError("meta_entry_invalid")
    if identifier(row["id"]) != context.conversation:
        raise IntakeError("meta_account_scope_mismatch")
    return row


def _one(rows, projection):
    if type(rows) is not list or len(rows) != 1:
        projection.problem = "meta_batch_requires_review"
        return None
    if type(rows[0]) is not dict:
        raise IntakeError("meta_update_invalid")
    return rows[0]


def _conversation(*parts):
    # Stable bounded scope even when both documented IDs are 128 bytes.
    return digest(*parts)


def _messaging(entry, projection, context):
    if "standby" in entry or "changes" in entry:
        projection.problem = "meta_unsupported_update_requires_review"
        return
    event = _one(entry.get("messaging"), projection)
    if event is None:
        return
    sender = identifier(event["sender"]["id"])
    recipient = identifier(event["recipient"]["id"])
    if recipient != context.conversation or sender == recipient:
        raise IntakeError("meta_sender_scope_invalid")
    message = event.get("message")
    if type(message) is not dict:
        projection.problem = "meta_nonmessage_requires_review"
        return
    projection.event_id = projection.message_id = identifier(message["mid"])
    projection.sender = sender
    projection.conversation = _conversation(context.conversation, sender)
    if message.get("is_echo") is not False and "is_echo" in message:
        projection.problem = "meta_echo_requires_review"
        return
    if "attachments" in message or "quick_reply" in message:
        projection.problem = "meta_media_or_action_requires_review"
        return
    if "reply_to" in message or "edit" in message or "is_deleted" in message:
        projection.problem = "meta_reply_or_edit_requires_review"
        return
    projection.original_text = text(message["text"])


def _facebook(entry, projection, context):
    if "messaging" in entry or "standby" in entry:
        projection.problem = "meta_unsupported_update_requires_review"
        return
    change = _one(entry.get("changes"), projection)
    if change is None:
        return
    if change.get("field") != "feed":
        projection.problem = "meta_unsupported_update_requires_review"
        return
    value = change["value"]
    if type(value) is not dict:
        raise IntakeError("meta_comment_invalid")
    if value.get("item") != "comment" or value.get("verb") != "add":
        projection.problem = "meta_nonnew_comment_requires_review"
        return
    sender = identifier(value["from"]["id"])
    if sender == context.conversation:
        projection.problem = "meta_page_self_event_requires_review"
        return
    post = identifier(value["post_id"])
    comment = identifier(value["comment_id"])
    projection.event_id = projection.message_id = comment
    projection.sender = sender
    projection.display_name = value["from"].get("name", "")[:256] if type(value["from"].get("name")) is str else ""
    projection.conversation = _conversation(context.conversation, post)
    # Meta parent_id can name a post or a different comment. Preserve the
    # original and require human thread review, never infer FOLLOWUP linkage.
    if "parent_id" in value or "parent_comment_id" in value:
        projection.problem = "meta_reply_requires_review"
        return
    if "attachments" in value or "photo" in value or "video" in value:
        projection.problem = "meta_media_or_action_requires_review"
        return
    projection.original_text = text(value["message"])



def _instagram_comments(entry, projection, context):
    """One IG professional-account media comment, not an inferred mention/reply."""
    change = _one(entry.get("changes"), projection)
    if change is None:
        return
    if change.get("field") != "comments":
        projection.problem = "meta_unsupported_update_requires_review"
        return
    value = change["value"]
    if type(value) is not dict or type(value.get("from")) is not dict:
        raise IntakeError("meta_comment_invalid")
    comment = identifier(value["id"])
    media = identifier(value["media"]["id"])
    sender = identifier(value["from"]["id"])
    projection.event_id = projection.message_id = comment
    projection.sender = sender
    name = value["from"].get("username")
    projection.display_name = name[:256] if type(name) is str else ""
    projection.conversation = _conversation(context.conversation, media)
    if sender == context.conversation:
        projection.problem = "meta_page_self_event_requires_review"
        return
    # Retain the precise original bytes and text without importing a new case.
    projection.original_text = text(value["text"])
    if "parent_id" in value:
        # The parent may be a comment by a different user, or a thread to which
        # this case has no current entitlement. Keep it for independent review.
        projection.parent_id = identifier(value["parent_id"])
        projection.problem = "meta_reply_requires_review"



def _whatsapp(entry, projection, context):
    change = _one(entry.get("changes"), projection)
    if change is None:
        return
    if change.get("field") != "messages":
        projection.problem = "meta_unsupported_update_requires_review"
        return
    value = change["value"]
    if type(value) is not dict:
        raise IntakeError("meta_whatsapp_value_invalid")
    if value.get("messaging_product") != "whatsapp":
        raise IntakeError("meta_messaging_product_invalid")
    phone_id = identifier(value["metadata"]["phone_number_id"])
    if phone_id != context.resource_id:
        raise IntakeError("meta_phone_scope_mismatch")
    if "statuses" in value or "errors" in value:
        projection.problem = "meta_status_or_error_requires_review"
        return
    message = _one(value.get("messages"), projection)
    if message is None:
        return
    sender = identifier(message["from"])
    mid = identifier(message["id"])
    projection.event_id = projection.message_id = mid
    projection.sender = sender
    projection.conversation = _conversation(phone_id, sender)
    if message.get("type") != "text" or "interactive" in message or "referral" in message:
        projection.problem = "meta_nontext_requires_review"
        return
    if "context" in message:
        # Context references need a separately reviewed parent/sender binding.
        projection.problem = "meta_reply_requires_review"
        return
    projection.original_text = text(message["text"]["body"])


def project_meta(data, projection, context):
    """Accept one unambiguous source object or hold *all* original bytes.

    No provider endpoints or access grants are inferred from the payload.
    """
    entry = _entry(data, context, projection)
    if entry is None:
        return
    if context.source == "messenger":
        _messaging(entry, projection, context)
    elif context.source == "instagram":
        has_messages = "messaging" in entry
        has_changes = "changes" in entry
        if has_messages == has_changes:
            projection.problem = "meta_unsupported_update_requires_review"
        elif has_messages:
            _messaging(entry, projection, context)
        else:
            _instagram_comments(entry, projection, context)
    elif context.source == "facebook":
        _facebook(entry, projection, context)
    elif context.source == "whatsapp":
        _whatsapp(entry, projection, context)
    else:
        raise IntakeError("meta_source_invalid")
