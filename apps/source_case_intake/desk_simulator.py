"""Server-generated fixture scenarios over existing source contracts, without network I/O."""

import json
import re

from django.conf import settings

from . import desk_services, services, simulators
from .adapters import IntakeError, SourceContext, digest

SCENARIOS = {
    "reply": "تعقيب اصطناعي من السائل نفسه",
    "other_sender": "رد اصطناعي من هوية أخرى تحمل الاسم نفسه",
    "unknown_parent": "رد اصطناعي على رسالة غير موجودة",
    "replay": "إعادة الحدث نفسه لاختبار منع التكرار",
}


def simulate(*, receipt_id, scenario, nonce, subject_id, provider, synthetic_fixtures_only=False):
    if getattr(settings, "FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED", False) is not True:
        raise IntakeError("source_simulator_disabled")
    services._guard(synthetic_fixtures_only)
    services._reviewer(provider, subject_id)
    if (
        scenario not in SCENARIOS
        or type(nonce) is not str
        or re.fullmatch("[0-9a-f]{32}", nonce) is None
    ):
        raise IntakeError("invalid_simulator_scenario")
    # Both the case scope and queue scope must be current. No input supplies a
    # person, arbitrary raw event, account, token, source ID or case grant.
    selected = desk_services.detail(
        receipt_id=receipt_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=True,
    )
    if not selected["receipt"]["case_id"]:
        raise IntakeError("bound_source_required")
    row = services._receipt(receipt_id)
    context = SourceContext(
        row.source, row.account, row.conversation if row.source == "youtube" else ""
    )
    raw = bytes(row.raw)
    if scenario != "replay":
        key = digest(str(row.pk), nonce, scenario, provider.provider_id, subject_id)
        number = 1_000_000_000 + int(key[:7], 16)
        missing = str(number + 1000)
        if row.source == "telegram":
            try:
                sender, chat, parent = int(row.sender), int(row.conversation), int(row.message_id)
                thread = int(row.thread) if row.thread else None
            except ValueError as exc:
                raise IntakeError("unsupported_source_fixture") from exc
            if scenario == "other_sender":
                sender = number if sender != number else number + 1
            data = json.loads(
                simulators.telegram(number, sender, parent, thread=thread, document=True)
            )
            data["message"]["chat"]["id"] = chat
            data["message"]["reply_to_message"]["chat"]["id"] = chat
            data["message"]["from"]["first_name"] = row.display_name
            data["message"]["document"]["file_id"] = "synthetic-file-" + key[:16]
            if scenario == "unknown_parent":
                data["message"]["reply_to_message"]["message_id"] = int(missing)
        elif row.source == "youtube":
            data = json.loads(simulators.youtube(number, row.sender))
            data["snippet"]["parentId"] = row.message_id
            data["snippet"]["authorDisplayName"] = row.display_name
            if scenario == "other_sender":
                data["snippet"]["authorChannelId"]["value"] = "synthetic-other-" + key[:16]
            if scenario == "unknown_parent":
                data["snippet"]["parentId"] = "synthetic-missing-" + key[:16]
        else:
            data = json.loads(simulators.website(number, row.sender))
            data["conversation_id"] = row.conversation
            data["display_name"] = row.display_name
            data["reply_to"] = row.message_id
            if scenario == "other_sender":
                data["session_subject"] = "synthetic-other-" + key[:16]
            if scenario == "unknown_parent":
                data["reply_to"] = "synthetic-missing-" + key[:16]
        raw = simulators.raw(data)
    # Recheck just before capture. Persistence keeps its independent-commit rule;
    # failed apply retains the raw receipt for an authorized later resume.
    services._reviewer(provider, subject_id)
    desk_services.detail(
        receipt_id=row.pk, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
    )
    result = services.ingest(raw=raw, context=context, synthetic_fixtures_only=True)
    result.pop("token")
    return result
