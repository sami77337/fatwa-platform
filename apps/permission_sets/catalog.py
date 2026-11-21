"""One closed operational matrix; no scientific, identity or policy-administration grant."""

import json
import re
import uuid
from hashlib import sha256

from apps.casework import services as cases
from apps.casework.models import Case
from apps.mufti_review.identity import _ref

DOMAIN = "OPERATIONAL"
MAX_RULES = 64
MAX_SETS = 16
MAX_CANDIDATES = 128
MAX_RESOURCES = 2048
ZERO = "0" * 64

SECTIONS = {
    "READ_QUEUE": "queue",
    "READ_CASE": "case",
    "READ_METADATA": "metadata",
    "READ_DELIVERY": "delivery",
    "READ_PUBLICATION": "publication",
    "READ_TRANSCRIPT": "transcript",
    "READ_CAPABILITY": "capability",
    "READ_INTERNAL_NOTES": "internal_notes",
    "ADD_INTERNAL_NOTE": "internal_notes",
    "EDIT_TAGS": "metadata",
    "EDIT_QUESTION_TYPES": "metadata",
    "READ_LESSON_LINKS": "lesson_links",
    "READ_TRANSCRIPT_EDITOR": "transcript_editor",
    "READ_PUBLICATION_MANAGER": "publication_manager",
}

KINDS = {
    **{key: {"CASE_OPERATIONAL_SECTION"} for key in SECTIONS},
    "READ_CLASSIFICATION": {"CASE_CLASSIFICATION_VERSION"},
    "BIND_CLASSIFICATION": {"CASE_CLASSIFICATION_VERSION"},
    "READ_COORDINATION": {"CASE_COORDINATION"},
    "SET_PRIMARY": {"CASE_COORDINATION"},
    "CLEAR_PRIMARY": {"CASE_COORDINATION"},
    "SET_PRIORITY": {"CASE_COORDINATION"},
    "READ_OPERATIONAL_LESSON": {"CASE_LESSON_VERSION"},
    "READ_LESSON_LINK": {"CASE_LESSON_LINK"},
    "PROPOSE_LESSON_LINK": {"CASE_LESSON_VERSION"},
    "APPROVE_LESSON_LINK": {"CASE_LESSON_LINK"},
    "REJECT_LESSON_LINK": {"CASE_LESSON_LINK"},
    "WITHDRAW_LESSON_LINK": {"CASE_LESSON_LINK"},
    "READ_RECORDING_TRANSCRIPT": {"CASE_RECORDING_SOURCE", "CASE_RECORDING_TRANSCRIPT"},
    "EDIT_RECORDING_TRANSCRIPT": {"CASE_RECORDING_SOURCE", "CASE_RECORDING_TRANSCRIPT"},
    "REVIEW_RECORDING_TRANSCRIPT": {"CASE_RECORDING_TRANSCRIPT"},
    "WITHDRAW_RECORDING_TRANSCRIPT": {"CASE_RECORDING_TRANSCRIPT"},
    "READ_RECORDING_AUDIO": {"CASE_RECORDING_SOURCE"},
    "READ_PUBLICATION_EDITION": {"CASE_PUBLICATION_EDITION"},
    "REVIEW_PUBLICATION_EDITION": {"CASE_PUBLICATION_EDITION"},
    "APPROVE_PUBLICATION_EDITION": {"CASE_PUBLICATION_EDITION"},
    "WITHDRAW_PUBLICATION_EDITION": {"CASE_PUBLICATION_EDITION"},
}

LABELS = {
    "READ_QUEUE": "عرض قائمة القضايا",
    "READ_CASE": "قراءة القضية",
    "READ_METADATA": "عرض البيانات التنظيمية",
    "READ_DELIVERY": "عرض حالة التوصيل",
    "READ_PUBLICATION": "عرض حالة النشر",
    "READ_TRANSCRIPT": "عرض حالة التفريغ",
    "READ_CAPABILITY": "عرض خيارات التوصيل",
    "READ_INTERNAL_NOTES": "قراءة الملاحظات الداخلية",
    "ADD_INTERNAL_NOTE": "إضافة ملاحظة داخلية",
    "EDIT_TAGS": "تعديل الوسوم",
    "EDIT_QUESTION_TYPES": "تعديل أنواع السؤال",
    "READ_LESSON_LINKS": "عرض مساحة روابط الدروس",
    "READ_TRANSCRIPT_EDITOR": "عرض مساحة تحرير التفريغ",
    "READ_PUBLICATION_MANAGER": "عرض مساحة إدارة نسخة النشر",
    "READ_CLASSIFICATION": "عرض نسخة التصنيف",
    "BIND_CLASSIFICATION": "ربط القضية بنسخة التصنيف",
    "READ_COORDINATION": "عرض الإسناد والأولوية",
    "SET_PRIMARY": "تعيين الشيخ الأساسي المحدد",
    "CLEAR_PRIMARY": "رفع الإسناد المحدد",
    "SET_PRIORITY": "اختيار الأولوية المحددة",
    "READ_OPERATIONAL_LESSON": "قراءة بيانات نسخة الدرس",
    "READ_LESSON_LINK": "قراءة رابط الدرس",
    "PROPOSE_LESSON_LINK": "اقتراح ربط نسخة الدرس",
    "APPROVE_LESSON_LINK": "اعتماد الربط التنظيمي بالدرس",
    "REJECT_LESSON_LINK": "رفض رابط الدرس",
    "WITHDRAW_LESSON_LINK": "سحب رابط الدرس",
    "READ_RECORDING_TRANSCRIPT": "قراءة التفريغ المشتق",
    "EDIT_RECORDING_TRANSCRIPT": "تحرير التفريغ المشتق",
    "REVIEW_RECORDING_TRANSCRIPT": "مراجعة التفريغ تحريريا",
    "WITHDRAW_RECORDING_TRANSCRIPT": "سحب نسخة التفريغ",
    "READ_RECORDING_AUDIO": "الاستماع إلى التسجيل المحدد",
    "READ_PUBLICATION_EDITION": "قراءة نسخة النشر",
    "REVIEW_PUBLICATION_EDITION": "مراجعة نسخة النشر",
    "APPROVE_PUBLICATION_EDITION": "اعتماد النسخة تحريريا للنشر",
    "WITHDRAW_PUBLICATION_EDITION": "سحب نسخة النشر",
}


class PermissionDenied(cases.CaseConflict):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def identifier(value):
    if type(value) is not str or not _ref(value):
        raise PermissionDenied("permission_identifier_invalid")
    return value


def uuid_text(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise PermissionDenied("permission_resource_invalid") from exc
    return value


def text(value, bound, *, empty=False):
    if (
        type(value) is not str
        or len(value) > bound
        or (not empty and not value.strip())
        or any(ord(c) < 32 and c not in "\r\n\t" for c in value)
    ):
        raise PermissionDenied("permission_text_invalid")
    return value.strip()


def scope(value):
    if (
        type(value) is not dict
        or set(value) != {"domain", "case_ref", "action", "resource"}
        or value["domain"] != DOMAIN
        or type(value["action"]) is not str
        or value["action"] not in KINDS
    ):
        raise PermissionDenied("permission_scope_invalid")
    identifier(value["case_ref"])
    action, resource = value["action"], value["resource"]
    if (
        type(resource) is not dict
        or type(resource.get("kind")) is not str
        or resource["kind"] not in KINDS[action]
    ):
        raise PermissionDenied("permission_resource_invalid")
    kind = resource["kind"]
    expected = {"kind", "case_id"}
    if kind == "CASE_OPERATIONAL_SECTION":
        expected |= {"section"}
        if resource.get("section") != SECTIONS[action]:
            raise PermissionDenied("permission_resource_invalid")
    elif kind == "CASE_CLASSIFICATION_VERSION":
        expected |= {"tree_case_id", "tree_id", "version_id", "digest"}
    elif kind == "CASE_COORDINATION":
        expected |= {
            "READ_COORDINATION": set(),
            "SET_PRIMARY": {"target", "target_epoch"},
            "CLEAR_PRIMARY": {"target"},
            "SET_PRIORITY": {"priority", "label", "rank", "policy_sha256"},
        }[action]
    elif kind in {"CASE_LESSON_VERSION", "CASE_LESSON_LINK"}:
        expected |= {"target_case_id", "version_id", "version_sha256"}
        if kind == "CASE_LESSON_LINK":
            expected |= {"link_id", "link_sha256"}
    elif kind in {"CASE_RECORDING_SOURCE", "CASE_RECORDING_TRANSCRIPT"}:
        expected |= {"part_id", "part_sha256"}
        if kind == "CASE_RECORDING_TRANSCRIPT":
            expected |= {"transcript_id", "transcript_digest"}
    elif kind == "CASE_PUBLICATION_EDITION":
        expected |= {"edition_id", "content_sha256", "answer_id", "decision_id", "evidence_version"}
    if set(resource) != expected:
        raise PermissionDenied("permission_resource_invalid")
    for key, item in resource.items():
        if key.endswith("_id"):
            uuid_text(item)
        elif key.endswith(("_sha256", "_digest")) or key == "digest":
            if type(item) is not str or re.fullmatch("[a-f0-9]{64}", item) is None:
                raise PermissionDenied("permission_resource_invalid")
        elif key in {"target", "target_epoch", "priority"}:
            identifier(item)
        elif key == "label":
            if text(item, 128) != item:
                raise PermissionDenied("permission_resource_invalid")
        elif key == "rank" and (type(item) is not int or not 0 <= item <= 100):
            raise PermissionDenied("permission_resource_invalid")
        elif key == "evidence_version" and (type(item) is not int or item < 1):
            raise PermissionDenied("permission_resource_invalid")
    return json.loads(canonical(value))


def rule(value):
    if (
        type(value) is not dict
        or set(value) != {"scope", "effect"}
        or type(value["effect"]) is not str
        or value["effect"] not in {"ALLOW", "DENY"}
    ):
        raise PermissionDenied("permission_rule_invalid")
    return {"scope": scope(value["scope"]), "effect": value["effect"]}


def rules(values):
    if type(values) is not list or len(values) > MAX_RULES:
        raise PermissionDenied("permission_rule_bound")
    result = [rule(value) for value in values]
    keys = [digest(value["scope"]) for value in result]
    if len(keys) != len(set(keys)):
        raise PermissionDenied("permission_duplicate_rule")
    return sorted(result, key=lambda value: digest(value["scope"]))


def definition(kind, value):
    if type(value) is not dict:
        raise PermissionDenied("permission_definition_invalid")
    if kind == "SET":
        if set(value) != {"title", "rules"}:
            raise PermissionDenied("permission_definition_invalid")
        return {"title": text(value["title"], 160), "rules": rules(value["rules"])}
    if kind != "USER" or set(value) != {"sets", "overrides"}:
        raise PermissionDenied("permission_definition_invalid")
    selected = value["sets"]
    if (
        type(selected) is not list
        or len(selected) > MAX_SETS
        or any(type(key) is not str for key in selected)
        or len(selected) != len(set(selected))
    ):
        raise PermissionDenied("permission_set_selection_invalid")
    return {
        "sets": sorted(uuid_text(key) for key in selected),
        "overrides": rules(value["overrides"]),
    }


def verify_scope(value):
    """Pure current source verification; it grants no read of source contents."""
    value = scope(value)
    resource = value["resource"]
    case = Case.objects.filter(pk=resource["case_id"]).first()
    if case is None or case.public_ref != value["case_ref"]:
        raise PermissionDenied("permission_case_changed")
    refs, expected = {case.public_ref}, resource
    kind = resource["kind"]
    if kind == "CASE_CLASSIFICATION_VERSION":
        from apps.development_taxonomy.models import TreeVersion
        from apps.operational_workspace.metadata import resource as build

        row = (
            TreeVersion.objects.select_related("tree__case")
            .filter(pk=resource["version_id"])
            .first()
        )
        if row is None:
            raise PermissionDenied("permission_resource_changed")
        expected = build(case, row)
        refs.add(row.tree.case.public_ref)
    elif kind in {"CASE_LESSON_VERSION", "CASE_LESSON_LINK"}:
        from apps.operational_workspace.lesson_links import resource as build
        from apps.scholarly_links.models import CaseLessonLink, LessonVersion

        row = (
            LessonVersion.objects.select_related("lesson__series__case")
            .filter(pk=resource["version_id"])
            .first()
        )
        if row is None:
            raise PermissionDenied("permission_resource_changed")
        link = None
        if kind == "CASE_LESSON_LINK":
            link = CaseLessonLink.objects.filter(
                pk=resource["link_id"], case=case, lesson_version=row
            ).first()
            if link is None:
                raise PermissionDenied("permission_resource_changed")
        target = row.lesson.series.case
        expected = build(case, target, row, link)
        refs.add(target.public_ref)
    elif kind in {"CASE_RECORDING_SOURCE", "CASE_RECORDING_TRANSCRIPT"}:
        from apps.answer_media.models import AnswerPart
        from apps.operational_workspace.transcripts import resource as build
        from apps.public_answer_media.models import RecordingTranscript

        part = AnswerPart.objects.filter(
            pk=resource["part_id"], manifest__answer__case=case, kind="AUDIO"
        ).first()
        if part is None:
            raise PermissionDenied("permission_resource_changed")
        transcript = None
        if kind == "CASE_RECORDING_TRANSCRIPT":
            transcript = RecordingTranscript.objects.filter(
                pk=resource["transcript_id"], case=case, part=part
            ).first()
            if transcript is None:
                raise PermissionDenied("permission_resource_changed")
        expected = build(case, part, transcript)
    elif kind == "CASE_PUBLICATION_EDITION":
        from apps.experimental_publication.models import PublicationEdition
        from apps.operational_workspace.publication import resource as build

        row = PublicationEdition.objects.filter(pk=resource["edition_id"], case=case).first()
        if row is None:
            raise PermissionDenied("permission_resource_changed")
        expected = build(case, row)
    if expected != resource:
        raise PermissionDenied("permission_resource_changed")
    return frozenset(refs)


def display(value):
    value = scope(value)
    resource = value["resource"]
    precise = next(
        (
            resource[key][:8]
            for key in ("edition_id", "transcript_id", "link_id", "version_id", "part_id")
            if key in resource
        ),
        "",
    )
    return {
        "key": digest(value),
        "label": LABELS[value["action"]],
        "case_ref": value["case_ref"],
        "resource_label": precise,
        "scope": value,
    }
