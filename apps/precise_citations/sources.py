"""Exact live sources; stored pins never contain a private source's text or bytes."""

from urllib.parse import urlsplit

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.research_library import services as library
from apps.research_library.models import LibraryVersion

from .boundary import digest

MODES = {"TEXT", "PAGE", "TIME", "METADATA"}


def text(value, limit, *, optional=False):
    cases._text(value, optional=optional)
    if len(value) > limit:
        raise cases.CaseConflict("precise_citation_text_bound")
    return value


def external(title, edition, location, url="", limitation=""):
    text(title, 200)
    text(edition, 200, optional=True)
    text(location, 1000, optional=True)
    text(limitation, 1000)
    text(url, 2000, optional=True)
    if url:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(char.isspace() or ord(char) < 32 for char in url)
        ):
            raise cases.CaseConflict("precise_citation_external_url_invalid")
    return {
        "title": title,
        "edition": edition,
        "location": location,
        "url": url,
        "limitation": limitation,
    }


def locator(mode="METADATA", start=0, end=0, label="", limitation=""):
    if mode not in MODES or type(start) is not int or type(end) is not int or min(start, end) < 0:
        raise cases.CaseConflict("precise_citation_locator_invalid")
    text(label, 200, optional=True)
    text(limitation, 1000, optional=mode != "METADATA")
    if mode == "METADATA" and (start or end):
        raise cases.CaseConflict("precise_citation_locator_invalid")
    return {"mode": mode, "start": start, "end": end, "label": label, "limitation": limitation}


def validate_pin(pin):
    if type(pin) is not dict or set(pin) != {
        "kind",
        "id",
        "case_id",
        "digest",
        "number",
        "part_id",
        "locator",
        "external",
    }:
        raise cases.CaseConflict("precise_citation_source_invalid")
    if pin["kind"] not in {"LIBRARY", "ANSWER", "EXTERNAL"}:
        raise cases.CaseConflict("precise_citation_source_invalid")
    if (
        type(pin["digest"]) is not str
        or len(pin["digest"]) != 64
        or set(pin["digest"]) - set("abcdef0123456789")
    ):
        raise cases.CaseConflict("precise_citation_source_invalid")
    if type(pin["number"]) is not int or not 1 <= pin["number"] <= 1000000:
        raise cases.CaseConflict("precise_citation_source_invalid")
    location = pin["locator"]
    if type(location) is not dict or set(location) != {
        "mode",
        "start",
        "end",
        "label",
        "limitation",
    }:
        raise cases.CaseConflict("precise_citation_locator_invalid")
    locator(**location)
    if pin["kind"] == "EXTERNAL":
        if pin["id"] or pin["case_id"] or pin["part_id"] or location["mode"] != "METADATA":
            raise cases.CaseConflict("precise_citation_external_invalid")
        if type(pin["external"]) is not dict or set(pin["external"]) != {
            "title",
            "edition",
            "location",
            "url",
            "limitation",
        }:
            raise cases.CaseConflict("precise_citation_external_invalid")
        external(**pin["external"])
        if pin["digest"] != digest(pin["external"]) or pin["number"] != 1:
            raise cases.CaseConflict("precise_citation_external_invalid")
    else:
        cases._uuid(pin["id"]), cases._uuid(pin["case_id"])
        if pin["part_id"]:
            cases._uuid(pin["part_id"])
        if pin["external"]:
            raise cases.CaseConflict("precise_citation_source_invalid")


def _material(guard, pin, usage):
    base = guard.library(pin["case_id"])
    row = (
        LibraryVersion.objects.select_related("item", "blob")
        .filter(pk=cases._uuid(pin["id"]), item__case_id=cases._uuid(pin["case_id"]))
        .first()
    )
    if row is None:
        raise cases.CaseConflict("precise_citation_source_unavailable")
    source = (
        library.authorize_material(version_id=row.pk, usage="READ", **base)
        if row.blob_id
        else library.read_material(version_id=row.pk, **base)
    )
    library.authorize_material(version_id=row.pk, usage="CITE", **base)
    if usage == "EXPORT":
        library.authorize_material(version_id=row.pk, usage="EXPORT", **base)
    if source["digest"] != pin["digest"] or row.number != pin["number"] or pin["part_id"]:
        raise cases.CaseConflict("precise_citation_source_changed")
    content = row.payload["recorded_text"] if row.blob_id else ""
    raw = b""
    if row.blob_id:
        raw = library._raw(row.blob)
        if row.blob.media_type == "application/pdf":
            # The validated original parser calls this field `pages`; the
            # general library DTO deliberately exposes only selected metadata.
            source["file"]["page_count"] = row.blob.validation.get("pages", 0)
        if (
            row.blob.media_type == "text/plain; charset=utf-8"
            or row.blob.media_type == "text/plain"
        ):
            content = raw.decode("utf-8")
    return {
        "title": row.payload["title"],
        "version": row.payload["edition_label"] or str(row.number),
        "text": content,
        "raw": raw,
        "file": source["file"],
        "corrections": [],
        "source_description": row.payload["source_locator"],
    }


def _answer(guard, pin, usage):
    case, _ = guard.actor(pin["case_id"])
    row = AnswerRevision.objects.filter(
        pk=cases._uuid(pin["id"]), case=case, decision__action="APPROVE"
    ).first()
    if row is None or row.text_sha256 != cases._digest(row.text) or row.revision != pin["number"]:
        raise cases.CaseConflict("precise_citation_source_unavailable")
    content, raw, file, identity = row.text, b"", None, row.text_sha256
    if pin["part_id"]:
        from apps.answer_media.models import AnswerPart
        from apps.answer_media.services import _verified, raw_for_part

        part = (
            AnswerPart.objects.select_related("manifest")
            .filter(pk=cases._uuid(pin["part_id"]), manifest__answer=row)
            .first()
        )
        if part is None:
            raise cases.CaseConflict("precise_citation_part_unavailable")
        _verified(part.manifest)
        raw = raw_for_part(part)
        identity = part.sha256
        content = raw.decode("utf-8") if part.kind == "TEXT" else ""
        file = {
            "sha256": part.sha256,
            "size": part.size,
            "media_type": part.media_type,
            "filename": part.filename,
            **part.metadata,
        }
        guard.media.append(part)
    if identity != pin["digest"]:
        raise cases.CaseConflict("precise_citation_source_changed")
    corrections = []
    for value in case.answers.filter(
        revision__gt=row.revision, decision__action="APPROVE"
    ).order_by("revision")[:64]:
        try:
            guard.permit(case.pk, "READ_SOURCE", "ANSWER", value.pk, value.text_sha256)
        except cases.CaseConflict:
            continue
        if value.text_sha256 != cases._digest(value.text):
            raise cases.CaseConflict("precise_citation_correction_changed")
        corrections.append(
            {
                "answer_id": str(value.pk),
                "number": value.revision,
                "text": value.text,
                "digest": value.text_sha256,
            }
        )
    return {
        "title": f"جواب سابق — {case.public_ref}",
        "version": f"إصدار {row.revision}",
        "text": content,
        "raw": raw,
        "file": file,
        "corrections": corrections,
        "source_description": "الاستشهاد بهذه النسخة لا يعتمد انطباق الحكم على قضية أخرى.",
    }


def read(guard, pin, *, owner_case_id, usage="READ"):
    validate_pin(pin)
    source_case = pin["case_id"] or owner_case_id
    resource_id = pin["part_id"] or pin["id"]
    resource_kind = "ANSWER_PART" if pin["part_id"] else pin["kind"]
    guard.permit(source_case, "CITE_SOURCE", resource_kind, resource_id, pin["digest"])
    guard.permit(
        source_case,
        "EXPORT_SOURCE" if usage == "EXPORT" else "READ_SOURCE",
        resource_kind,
        resource_id,
        pin["digest"],
    )
    if pin["kind"] == "LIBRARY":
        result = _material(guard, pin, usage)
    elif pin["kind"] == "ANSWER":
        result = _answer(guard, pin, usage)
    else:
        entry = pin["external"]
        result = {
            "title": entry["title"],
            "version": entry["edition"],
            "text": "",
            "raw": b"",
            "file": None,
            "corrections": [],
            "source_description": entry["location"],
            "external_url": entry["url"],
        }
    at, content, file = pin["locator"], result["text"], result["file"]
    mode, start, end = at["mode"], at["start"], at["end"]
    if mode == "TEXT":
        if not 0 <= start < end <= len(content) or end - start > 4000:
            raise cases.CaseConflict("precise_citation_text_locator_unavailable")
        result.update(before=content[:start], selected=content[start:end], after=content[end:])
        location = f"محارف المصدر {start + 1}–{end}"
    elif mode == "PAGE":
        if not file or not 1 <= start == end <= file.get("page_count", file.get("pages", 0)):
            raise cases.CaseConflict("precise_citation_page_unavailable")
        location = f"صفحة الملف {start}" + (f"؛ تسمية بشرية: {at['label']}" if at["label"] else "")
    elif mode == "TIME":
        duration = (file or {}).get("duration_seconds", 0)
        if not file or not 0 <= start < end <= duration * 1000:
            raise cases.CaseConflict("precise_citation_time_unavailable")
        location = f"{start / 1000:g}–{end / 1000:g} ثانية"
    else:
        location = result["source_description"] or "مرجع وصفي دون موضع رقمي"
    result.update(
        locator=at,
        location=location,
        reference=f"{result['title']} — {result['version']} — {location}",
        limitation=at["limitation"],
        kind=pin["kind"],
        digest=pin["digest"],
    )
    result["media_fragment"] = f"#t={start / 1000:g},{end / 1000:g}" if mode == "TIME" else ""
    result["video"] = bool(file and file["media_type"].startswith("video/"))
    return result


def select(guard, selection, *, owner_case_id, location, part_id="", descriptor=None):
    if selection == "EXTERNAL":
        descriptor = external(**(descriptor or {}))
        pin = {
            "kind": "EXTERNAL",
            "id": "",
            "case_id": "",
            "digest": digest(descriptor),
            "number": 1,
            "part_id": "",
            "locator": location,
            "external": descriptor,
        }
    else:
        try:
            pieces = selection.split(":")
            if len(pieces) == 3:
                if part_id and part_id != pieces[2]:
                    raise cases.CaseConflict("precise_citation_part_changed")
                part_id = pieces.pop()
            kind, identifier = pieces
        except (ValueError, AttributeError) as exc:
            raise cases.CaseConflict("precise_citation_selection_invalid") from exc
        identifier = cases._uuid(identifier)
        if kind == "LIBRARY":
            row = LibraryVersion.objects.filter(pk=identifier).select_related("item").first()
            if row is None:
                raise cases.CaseConflict("precise_citation_source_unavailable")
            source_case, version, source_digest = row.item.case_id, row.number, row.digest
        elif kind == "ANSWER":
            row = AnswerRevision.objects.filter(pk=identifier).first()
            if row is None:
                raise cases.CaseConflict("precise_citation_source_unavailable")
            source_case, version, source_digest = row.case_id, row.revision, row.text_sha256
            if part_id:
                from apps.answer_media.models import AnswerPart

                part = AnswerPart.objects.filter(
                    pk=cases._uuid(part_id), manifest__answer=row
                ).first()
                if part is None:
                    raise cases.CaseConflict("precise_citation_part_unavailable")
                source_digest = part.sha256
        else:
            raise cases.CaseConflict("precise_citation_selection_invalid")
        pin = {
            "kind": kind,
            "id": str(identifier),
            "case_id": str(source_case),
            "digest": source_digest,
            "number": version,
            "part_id": str(part_id),
            "locator": location,
            "external": {},
        }
    return pin, read(guard, pin, owner_case_id=owner_case_id)


def choices(guard, owner_case_id):
    result = []
    # Only current actor-scoped cases, never the extra graph dependency cases.
    allowed = []
    for key in guard.locked:
        try:
            guard.actor(key)
        except cases.CaseConflict:
            continue
        allowed.append(key)
    for row in (
        LibraryVersion.objects.filter(item__case_id__in=allowed)
        .select_related("item")
        .order_by("pk")[:64]
    ):
        try:
            case, actor = guard.actor(row.item.case_id)
            policy = library.policy_snapshot()
            # Exclusions are probed without retaining a denied operation inside
            # an open source boundary. Successful selections are rechecked below.
            for action in ("CITE", "READ") if row.blob_id else ("CITE", "VIEW"):
                library._permit_raw(
                    policy[0],
                    dict(
                        provider_id=guard.provider.provider_id,
                        subject_id=actor.subject_id,
                        auth_epoch=actor.auth_epoch,
                        case_ref=case.public_ref,
                        action=action,
                        **library._fields(row),
                    ),
                )
                if action != "VIEW":
                    library._approval(row, action)
            library.assert_policy_snapshot(policy)
            guard.permit(row.item.case_id, "CITE_SOURCE", "LIBRARY", row.pk, row.digest)
        except cases.CaseConflict:
            continue
        dto = library.authorize_material(
            version_id=row.pk, usage="CITE", **guard.library(row.item.case_id)
        )
        if row.blob_id:
            library.authorize_material(
                version_id=row.pk, usage="READ", **guard.library(row.item.case_id)
            )
        result.append(
            {
                "selection": "LIBRARY:" + str(row.pk),
                "title": dto["payload"]["title"],
                "version": row.number,
            }
        )
    for row in AnswerRevision.objects.filter(
        case_id__in=allowed, decision__action="APPROVE"
    ).order_by("pk")[:64]:
        try:
            guard.permit(row.case_id, "CITE_SOURCE", "ANSWER", row.pk, row.text_sha256)
            guard.permit(row.case_id, "READ_SOURCE", "ANSWER", row.pk, row.text_sha256)
        except cases.CaseConflict:
            continue
        result.append(
            {
                "selection": "ANSWER:" + str(row.pk),
                "title": f"جواب سابق — {guard.locked[row.case_id].public_ref}",
                "version": row.revision,
            }
        )
        from apps.answer_media.models import AnswerPart

        for part in AnswerPart.objects.filter(manifest__answer=row).order_by("ordinal"):
            try:
                guard.permit(row.case_id, "CITE_SOURCE", "ANSWER_PART", part.pk, part.sha256)
                guard.permit(row.case_id, "READ_SOURCE", "ANSWER_PART", part.pk, part.sha256)
            except cases.CaseConflict:
                continue
            result.append(
                {
                    "selection": f"ANSWER:{row.pk}:{part.pk}",
                    "title": f"جزء {part.ordinal} ({part.kind}) — {guard.locked[row.case_id].public_ref}",
                    "version": row.revision,
                }
            )
    return result
