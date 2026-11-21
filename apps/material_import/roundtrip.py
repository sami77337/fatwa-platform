"""Explicitly selected, separately authorized material transfer; never restores grants."""

import io
import zipfile
from datetime import datetime, timedelta
from hashlib import sha256

from django.utils import timezone

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service
from apps.research_library import services as library

from . import formats, policy
from .models import RoundtripReceipt


def pin(value):
    return {
        key: value[key] for key in ("version_id", "digest", "namespace", "external_id", "number")
    }


def _selection(selected):
    if type(selected) is not list or not 1 <= len(selected) <= formats.MAX_ROWS:
        raise cases.CaseConflict("roundtrip_selection_required")
    seen, namespaces = set(), set()
    for row in selected:
        if (
            type(row) is not dict
            or set(row) != {"version_id", "digest", "namespace", "external_id", "number"}
            or type(row["number"]) is not int
            or not 1 <= row["number"] <= 64
            or type(row["digest"]) is not str
            or len(row["digest"]) != 64
        ):
            raise cases.CaseConflict("roundtrip_selection_invalid")
        key = str(cases._uuid(row["version_id"]))
        if key in seen:
            raise cases.CaseConflict("roundtrip_selection_duplicate")
        formats.identifier(row["namespace"])
        formats.identifier(row["external_id"])
        seen.add(key)
        namespaces.add(row["namespace"])
    if len(namespaces) != 1:
        raise cases.CaseConflict("roundtrip_single_namespace_required")
    return next(iter(namespaces))


def _timestamp(value):
    try:
        stamp = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise cases.CaseConflict("roundtrip_preview_invalid") from exc
    if (
        not timezone.is_aware(stamp)
        or stamp.utcoffset() != timedelta(0)
        or not timezone.now() - timedelta(minutes=15)
        <= stamp
        <= timezone.now() + timedelta(seconds=5)
    ):
        raise cases.CaseConflict("roundtrip_preview_expired")
    return stamp.isoformat()


def _build(selected, prepared_at, base):
    namespace = _selection(selected)
    prepared_at = _timestamp(prepared_at)
    records, members, files, origin, preview = [], {}, [], [], []
    for ordinal, chosen in enumerate(selected, 1):
        current = library.current_material(
            **base, namespace=namespace, external_id=chosen["external_id"]
        )
        if current is None or pin(current) != chosen:
            raise cases.CaseConflict("roundtrip_source_changed")
        authorized = library.authorize_material(
            **base, version_id=chosen["version_id"], usage="EXPORT"
        )
        if pin(authorized) != chosen:
            raise cases.CaseConflict("roundtrip_source_changed")
        payload = dict(authorized["payload"])
        if payload.pop("synthetic", None) is not True:
            raise cases.CaseConflict("roundtrip_synthetic_required")
        record = {
            "_synthetic": True,
            "external_id": chosen["external_id"],
            **payload,
            "file_member": "",
        }
        if authorized["file"]:
            content = library.file_content(**base, version_id=chosen["version_id"], usage="EXPORT")
            if (
                content["sha256"] != authorized["file"]["sha256"]
                or len(content["raw"]) != authorized["file"]["size"]
            ):
                raise cases.CaseConflict("roundtrip_file_changed")
            extension = content["filename"].rsplit(".", 1)[-1]
            path = f"files/{ordinal:02d}.{extension}"
            if formats.FILE_MEMBER.fullmatch(path) is None:
                raise cases.CaseConflict("roundtrip_file_name_invalid")
            record["file_member"] = path
            members[path] = content["raw"]
            files.append(
                {
                    "path": path,
                    "filename": content["filename"],
                    "media_type": content["media_type"],
                    "sha256": content["sha256"],
                    "size": len(content["raw"]),
                }
            )
        records.append(record)
        origin.append(
            {
                "external_id": chosen["external_id"],
                "source_item_id": current["item_id"],
                "source_version_id": chosen["version_id"],
                "source_number": chosen["number"],
                "source_digest": chosen["digest"],
                "record_sha256": formats.digest(record),
            }
        )
        preview.append(
            {
                "title": payload["title"],
                "external_id": chosen["external_id"],
                "kind": payload["kind"],
                "number": chosen["number"],
                "digest": chosen["digest"],
                "file": authorized["file"],
            }
        )
    manifest = {
        "schema": formats.SCHEMA,
        "synthetic": True,
        "records": "records.json",
        "files": files,
        "origin": {
            "schema": "fatwa.material-roundtrip.v1",
            "namespace": namespace,
            "prepared_at": prepared_at,
            "mapping": origin,
        },
    }
    members["records.json"] = formats.canonical(records)
    members["manifest.json"] = formats.canonical(manifest)
    if sum(map(len, members.values())) > formats.MAX_BYTES:
        raise cases.CaseConflict("roundtrip_size_exceeded")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(members):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, members[path])
    raw = output.getvalue()
    if len(raw) > formats.MAX_BYTES:
        raise cases.CaseConflict("roundtrip_size_exceeded")
    # Validate the actual emitted archive with the same strict admission parser.
    parsed = formats.parse(raw, "materials.zip")
    if parsed.origin["namespace"] != namespace or len(parsed.rows) != len(selected):
        raise cases.CaseConflict("roundtrip_reconciliation_failed")
    for chosen in selected:
        fresh = library.authorize_material(**base, version_id=chosen["version_id"], usage="EXPORT")
        if pin(fresh) != chosen:
            raise cases.CaseConflict("roundtrip_source_changed")
    return {
        "raw": raw,
        "sha256": sha256(raw).hexdigest(),
        "size": len(raw),
        "manifest": manifest,
        "preview": preview,
        "namespace": namespace,
        "prepared_at": prepared_at,
        "selected": selected,
    }


@mutation_service
def inventory(*, query="", kind="", page=1, **base):
    with policy.boundary(**base):
        result = library.browse(**base, query=query, kind=kind, page=page)
        result["choices"] = [
            {
                "pin": pin(row),
                "title": row["payload"]["title"],
                "kind": row["payload"]["kind"],
                "namespace": row["namespace"],
                "number": row["number"],
            }
            for row in result.pop("rows")
        ]
        return result


@mutation_service
def prepare(*, selected, **base):
    namespace = _selection(selected)
    with policy.boundary(**base, action="EXPORT", namespace=namespace):
        result = _build(selected, timezone.now().isoformat(), base)
        return {key: value for key, value in result.items() if key != "raw"}


@mutation_service
def revalidate(*, selected, prepared_at, expected_sha256, **base):
    namespace = _selection(selected)
    with policy.boundary(**base, action="EXPORT", namespace=namespace):
        result = _build(selected, prepared_at, base)
        if result["sha256"] != expected_sha256:
            raise cases.CaseConflict("roundtrip_preview_changed")
        return {key: value for key, value in result.items() if key != "raw"}


@mutation_service
def download(*, selected, prepared_at, expected_sha256, request_key, **base):
    namespace = _selection(selected)
    with policy.boundary(**base, action="EXPORT", namespace=namespace) as (case, actor):
        result = _build(selected, prepared_at, base)
        if result["sha256"] != expected_sha256:
            raise cases.CaseConflict("roundtrip_preview_changed")
        scope = {"selected": selected, "prepared_at": result["prepared_at"]}
        key = cases._uuid(request_key)
        existing = RoundtripReceipt.objects.filter(
            case=case,
            provider_id=base["provider"].provider_id,
            subject_id=actor.subject_id,
            request_key=key,
        ).first()
        if existing:
            if (
                existing.scope != scope
                or existing.scope_digest != formats.digest(scope)
                or existing.artifact_sha256 != result["sha256"]
                or existing.manifest != result["manifest"]
            ):
                raise cases.CaseConflict("roundtrip_request_conflict")
        else:
            if RoundtripReceipt.objects.filter(case=case).count() >= 32:
                raise cases.CaseConflict("roundtrip_receipt_capacity")
            RoundtripReceipt.objects.create(
                case=case,
                provider_id=base["provider"].provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                request_key=key,
                scope=scope,
                scope_digest=formats.digest(scope),
                manifest=result["manifest"],
                artifact_sha256=result["sha256"],
                size=result["size"],
            )
        return {
            "raw": result["raw"],
            "sha256": result["sha256"],
            "filename": "synthetic-material-roundtrip.zip",
        }
