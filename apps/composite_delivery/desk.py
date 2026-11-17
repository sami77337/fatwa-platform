"""Current-case staff control surface over the existing composite engine.

No worker, sender, queue or signing key lives here. Source IDs are opaque recorded
references, never a guessed external API address or a choice of another recipient.
"""

import json
from dataclasses import fields
from datetime import datetime
from hmac import compare_digest

from django.conf import settings
from django.utils import timezone

from apps.casework import delivery as legacy
from apps.casework import services as cases
from apps.delivery_planner.trusted_identity import canonical_plan_sha256
from apps.delivery_queue import approval_adapter as adapter
from apps.delivery_queue import services as queue
from apps.delivery_queue.author_handoff import decode_signed_response
from apps.delivery_queue.models import DeliveryAttempt, DeliveryIntent
from apps.delivery_queue.signed_provider_receipts import (
    Ed25519ProviderEventVerifier,
    SignedProviderEvent,
)

from . import services
from .models import CompositeDelivery

KINDS = {"TEXT": "نص", "FILE": "ملف", "AUDIO": "صوت", "IMAGE": "صورة"}
STATES = {
    "NOT_STAGED": "لم تُجهّز محاولة",
    "STAGED": "مجهز، لم يُرسل",
    "LEASED": "محجوز لمحاولة محلية",
    "SENT_UNCONFIRMED": "قبول المزود فقط؛ التسليم غير مؤكد",
    "DELIVERED": "أبلغ المزود عن التسليم",
    "FAILED_REQUIRES_REVIEW": "فشل يحتاج مراجعة بشرية",
    "UNKNOWN_REQUIRES_RECONCILIATION": "نتيجة غير محسومة",
}
SUMMARY_LABELS = {
    "STAGED": "جميع الأجزاء مجهزة ولم تُرسل",
    "IN_PROGRESS": "محاولات قيد المعالجة؛ التسليم غير مكتمل",
    "PARTIALLY_DELIVERED": "تسليم جزئي؛ بقية الأجزاء لم يثبت تسليمها",
    "PARTIALLY_FAILED": "تسليم جزئي مع فشل يحتاج مراجعة بشرية",
    "FAILED_REQUIRES_REVIEW": "فشل يحتاج مراجعة بشرية",
    "NEEDS_RECONCILIATION": "توجد نتائج غير محسومة تحتاج مطابقة",
    "DELIVERED": "أبلغ المزود عن تسليم جميع الأجزاء؛ تحقق التوقيع موضح أدناه",
}
REASONS = {
    "source_supports_part": "قدرات القناة تغطي هذا الجزء",
    "text_segmentation_required": "النص يتجاوز قدرة القناة؛ يلزم قرار بشري بشأن التقسيم",
    "unsupported_source_media": "القناة لا تقبل نوع هذا الجزء",
    "signed_delivery_receipts_unavailable": "القناة لا توفر إيصالات تسليم موقّعة",
    "unsupported_mime_or_size": "صيغة الملف أو حجمه خارج قدرة القناة",
}
BLOCKED = {
    "current_mufti_approval_required": "يلزم اعتماد بشري حالي للجواب وجميع أجزائه.",
    "composite_manifest_required": "هذا المكتب مخصص للجواب المركب؛ افتح مسار النص المعتمد للقضية.",
    "source_origin_schema_unavailable": "تعذر التحقق من أصل المصدر؛ لا تُستخدم قناة بديلة.",
    "source_origin_unavailable": "أصل القناة أو ربطه غير محسوم؛ يلزم حسم الربط في مكتب الاستقبال.",
    "source_origin_inconsistent": "أصل القناة أو ربطه غير محسوم؛ يلزم حسم الربط في مكتب الاستقبال.",
    "channel_capabilities_unavailable": "قدرات القناة غير متاحة للتحقق؛ التجهيز متوقف.",
    "invalid_synthetic_channel_capabilities": "قدرات القناة غير معتمدة لهذه التجربة؛ التجهيز متوقف.",
}
PROVIDER_BUNDLE_SCHEMA = "fatwa.composite-provider-evidence.v1"


def _origin(case):
    origin = cases._delivery_origin_for_locked_case(case)
    result = {
        **origin,
        "label": {
            "WEBSITE": "الموقع",
            "website": "الموقع",
            "telegram": "Telegram",
            "youtube": "YouTube",
        }.get(origin["channel"], origin["channel"]),
    }
    if case.source.source_event_id.startswith("source:"):
        # The canonical helper above verifies identity, raw hash and case binding.
        from apps.source_case_intake.models import EvidenceBinding

        row = (
            EvidenceBinding.objects.select_related("receipt")
            .get(
                case=case,
                evidence__version=1,
                action="CREATED",
            )
            .receipt
        )
        result.update(
            {
                key: getattr(row, key)
                for key in (
                    "account",
                    "conversation",
                    "thread",
                    "message_id",
                    "sender",
                    "sha256",
                )
            }
        )
    else:
        result.update(message_id=case.source.source_event_id)
    return result


def _read_locked(case, subject_id, provider):
    base = {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "blocked": "",
        "parts": [],
    }
    try:
        prepared = services._prepare(case, subject_id, provider)
    except cases.CaseConflict as exc:
        if str(exc) not in BLOCKED:
            raise
        return {**base, "blocked": BLOCKED[str(exc)]}
    decision, manifest, capability, evidence, plan = prepared
    origin = _origin(case)
    fingerprint = canonical_plan_sha256(plan)
    binding = CompositeDelivery.objects.select_related("approval").filter(decision=decision).first()
    permission_valid, status, rows = False, None, {}
    permission = "لم يُسجل إذن مستقل موقّع لتجهيز هذه الخطة."
    if binding:
        try:
            services._bound(case, subject_id, provider)
        except cases.CaseConflict:
            return {
                **base,
                "blocked": "تغيّرت الخطة أو قدرات القناة بعد تسجيل الإذن. يلزم إصدار واعتماد جديدان؛ لا إعادة إرسال.",
                "origin": origin,
            }
        rows = {
            row.ordinal: row for row in DeliveryIntent.objects.filter(approval=binding.approval)
        }
        try:
            adapter._verify_current_claim(
                binding.approval,
                getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None),
                services._reader(case, subject_id, provider, prepared),
            )
            permission_valid = True
            permission = "إذن مستقل موقّع متحقق لهذه الخطة الحالية."
        except ValueError:
            permission = (
                "الإذن محفوظ، لكن صلاحيته الحالية غير متحققة أو انتهت؛ لا حجز جديد من هذا المكتب."
            )
        verifier = getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None)
        if isinstance(verifier, Ed25519ProviderEventVerifier):
            status = services.composite_status(
                case_id=case.pk,
                subject_id=subject_id,
                provider=provider,
                verifier=verifier,
                synthetic_fixtures_only=True,
            )
    status_parts = {p["ordinal"]: p for p in status["parts"]} if status else {}
    parts = []
    for part, step in zip(manifest["parts"], plan.steps, strict=True):
        row = rows.get(part["ordinal"])
        proof = status_parts.get(part["ordinal"], {})
        state = row.state if row else "NOT_STAGED"
        attempt = DeliveryAttempt.objects.filter(intent=row).first() if row else None
        expired = bool(state == "LEASED" and attempt and attempt.expires_at <= timezone.now())
        verified = proof.get("delivery_verified", False)
        if step.action != "READY_FOR_ADAPTER":
            action = REASONS.get(step.reason, "يلزم قرار بشري بشأن قدرة القناة.")
        elif expired:
            action = "انتهت مهلة المحاولة. طابق الحجوزات لتسجيلها غير محسومة، دون إعادة إرسال."
        elif state in {"UNKNOWN_REQUIRES_RECONCILIATION", "SENT_UNCONFIRMED", "LEASED"}:
            action = "طابق إيصال المزود الموقّع مع هذه المحاولة؛ لا تُنشئ محاولة أخرى."
        elif state == "FAILED_REQUIRES_REVIEW":
            action = "راجع سبب الفشل عبر المسار البشري؛ إعادة المحاولة ليست متاحة هنا."
        elif state == "DELIVERED":
            action = (
                "لا إجراء مطلوب لهذا الجزء."
                if verified
                else "يلزم التحقق من دليل التسليم؛ الحالة وحدها ليست إثباتًا."
            )
        else:
            action = "بانتظار إذن مستقل وعامل تجريبي مخوّل؛ هذا المكتب لا يرسل."
        parts.append(
            {
                **part,
                "kind_label": KINDS[part["kind"]],
                "state": state,
                "state_label": STATES[state],
                "delivery_verified": verified,
                "capability_reason": REASONS.get(step.reason, "يلزم قرار بشري"),
                "supported": step.action == "READY_FOR_ADAPTER",
                "next_action": action,
                "expired": expired,
                "attempted": attempt is not None,
                "lease_expires_at": attempt.expires_at if attempt else None,
                "may_import": attempt is not None and state != "FAILED_REQUIRES_REVIEW",
                "envelope_sha256": step.idempotency_key,
            }
        )
    services._reader(case, subject_id, provider, prepared)(case.public_ref)
    return {
        **base,
        "origin": origin,
        "parts": parts,
        "plan_sha256": fingerprint,
        "answer_revision": evidence.answer_revision,
        "decision_id": str(decision.pk),
        "manifest_sha256": manifest["sha256"],
        "capability_sha256": capability,
        "plan_status": plan.status,
        "permission": permission,
        "permission_valid": permission_valid,
        "permission_expires_at": binding.approval.expires_at if binding else None,
        "staged": binding is not None,
        "status": status,
        "status_label": SUMMARY_LABELS[status["state"]] if status else "",
        "provider_verifier_available": status is not None if binding else False,
        "requires_human": plan.status != "PLANNED_NOT_SENT"
        or bool(status and status["human_action"]),
        "has_expired": any(p["expired"] for p in parts),
    }


def read_delivery_desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    services._enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        return _read_locked(case, subject_id, provider)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non_json_numeric_constant")


def decode_provider_bundle(raw):
    """Bounded offline worker handoff; secrets never returned to HTML or audit notes."""
    try:
        if type(raw) is not str or not 1 <= len(raw.encode()) <= 16000:
            raise ValueError()
        data = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        if type(data) is not dict or set(data) != {"schema", "part_id", "lease", "event"}:
            raise ValueError()
        if data["schema"] != PROVIDER_BUNDLE_SCHEMA or type(data["part_id"]) is not str:
            raise ValueError()
        lease = data["lease"]
        if type(lease) is not dict or set(lease) != {f.name for f in fields(queue.WorkerLease)}:
            raise ValueError()
        lease = dict(lease)
        lease["expires_at"] = datetime.fromisoformat(lease["expires_at"].replace("Z", "+00:00"))
        if not queue._utc(lease["expires_at"]):
            raise ValueError()
        if (
            not queue._hex(lease["intent_key"])
            or not queue._ref(lease["owner"])
            or type(lease["token"]) is not str
            or not 32 <= len(lease["token"]) <= 128
        ):
            raise ValueError()
        event = SignedProviderEvent(**data["event"])
        if any(
            (
                type(getattr(event, field.name)) is not int
                or not 1 <= getattr(event, field.name) <= 16
            )
            if field.name == "ordinal"
            else (
                type(getattr(event, field.name)) is not str or len(getattr(event, field.name)) > 512
            )
            for field in fields(SignedProviderEvent)
        ):
            raise ValueError()
        return data["part_id"], queue.WorkerLease(**lease), event
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError) as exc:
        raise cases.CaseConflict("invalid_provider_bundle") from exc


def apply_desk_action(
    *,
    case_id,
    subject_id,
    provider,
    action,
    revision,
    evidence_version,
    plan_sha256,
    response_json="",
    part_id="",
    synthetic_fixtures_only=False,
):
    """Optimistic case/plan check and action occur under the same case/queue locks."""
    services._enabled()
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        cases._versions(case, revision, evidence_version)
        prepared = services._prepare(case, subject_id, provider)
        if not queue._hex(plan_sha256) or not compare_digest(
            plan_sha256,
            canonical_plan_sha256(prepared[4]),
        ):
            raise cases.CaseConflict("composite_plan_changed")
        common = dict(
            case_id=case_id, subject_id=subject_id, provider=provider, synthetic_fixtures_only=True
        )
        if action == "composite_stage":
            digest, receipt = decode_signed_response(response_json)
            if not compare_digest(digest, plan_sha256):
                raise cases.CaseConflict("composite_plan_changed")
            services.stage_composite_delivery(
                **common,
                receipt=receipt,
                verify_receipt=getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None),
            )
            return "سُجلت خطة جميع الأجزاء بإذن مستقل. لم يحدث إرسال."
        if action == "composite_receipt":
            bundle_part, lease, event = decode_provider_bundle(response_json)
            part = next((p for p in prepared[1]["parts"] if p["id"] == part_id), None)
            if part is None or bundle_part != part_id or event.ordinal != part["ordinal"]:
                raise cases.CaseConflict("composite_part_mismatch")
            services.record_composite_event(
                **common,
                lease=lease,
                event=event,
                verifier=getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None),
            )
            return "حُفظ الإيصال الموقّع للجزء المحدد؛ لم تُنشأ محاولة جديدة."
        if action == "composite_reconcile":
            result = services.reconcile_composite_timeouts(**common)
            return f"سُجلت {result['unresolved_parts']} محاولة منتهية كغير محسومة؛ لا إعادة إرسال."
        if action == "composite_export":
            return services.prepare_composite_delivery(**common)
        raise cases.CaseConflict("unknown_composite_action")
