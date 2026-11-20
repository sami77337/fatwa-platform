"""Allowlisted records from the existing canonical readers, never arbitrary files."""

from dataclasses import asdict
from hashlib import sha256

from apps.casework import services as cases
from apps.research_workspace import services as research
from apps.research_workspace.rights import Resource, require

from . import policy
from .serialization import checked, digest

KINDS = {"REFERENCE", "TRANSCRIPT", "KNOWLEDGE", "ATTACHMENT", "ANSWER_MEDIA"}
MEDIA = {"ATTACHMENT", "ANSWER_MEDIA"}
SOURCE_FIELDS = (
    "edition_id",
    "source_row_id",
    "work_title",
    "heading_title",
    "printed_part",
    "printed_page",
    "path",
    "source_namespace",
    "source_book_id",
    "edition_key",
    "source_archive_sha256",
    "source_input_sha256",
    "edition_title",
    "publisher",
    "kind",
)
EXTENSIONS = {
    "text/plain": "txt",
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
}


def resource(value):
    if isinstance(value, Resource):
        value = asdict(value)
    if type(value) is not dict or set(value) != set(Resource.__dataclass_fields__):
        raise cases.CaseConflict("export_resource_invalid")
    if (
        any(type(v) is not str for k, v in value.items() if k != "edition_id")
        or value["kind"] not in KINDS
    ):
        raise cases.CaseConflict("export_resource_invalid")
    if value["edition_id"] is not None and type(value["edition_id"]) is not int:
        raise cases.CaseConflict("export_resource_invalid")
    if (
        len(value["identifier"]) > 100
        or len(value["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in value["sha256"])
    ):
        raise cases.CaseConflict("export_resource_invalid")
    return Resource(**value)


def permissions(case, actor, provider, selected, include_files):
    policy.permit(case, actor, provider, "EXPORT_RECORD", selected)
    if selected.kind != "REFERENCE":
        policy.permit(case, actor, provider, "EXPORT_SENSITIVE", selected)
    if include_files and selected.kind in MEDIA:
        policy.permit(case, actor, provider, "EXPORT_MEDIA", selected)


def read(*, case, actor, provider, selected, ordinal, include_files):
    selected = resource(selected)
    permissions(case, actor, provider, selected, include_files)
    if selected.kind in MEDIA and not include_files:
        row = media_metadata(case, actor, provider, selected)
        opened = {"media_type": row.media_type, "size": row.size}
    else:
        opened = research.open_resource(
            case_id=case.pk,
            subject_id=actor.subject_id,
            provider=provider,
            resource=selected,
            synthetic_fixtures_only=True,
        )
    record = dict(
        ordinal=ordinal,
        kind=selected.kind,
        identifier=selected.identifier,
        version_sha256=selected.sha256,
        metadata={},
        content=None,
        relationships=[],
        files=[],
    )
    files = {}
    if selected.kind == "REFERENCE":
        record["metadata"] = {
            key: opened["source"][key] for key in SOURCE_FIELDS if key in opened["source"]
        }
        record["metadata"]["material_type"] = "book-index-metadata-not-full-text"
    elif selected.kind == "TRANSCRIPT":
        record["metadata"] = {
            "source_id": opened["source_id"],
            "source_sha256": opened["source_sha256"],
            "input_sha256": opened["input_sha256"],
            "material_type": "source-transcript-not-approved-case-answer",
        }
        record["content"] = {
            name: {key: opened[name][key] for key in ("text", "start_ms", "end_ms")}
            if opened[name]
            else None
            for name in ("question", "answer")
        }
    elif selected.kind == "KNOWLEDGE":
        from apps.knowledge_links.models import KnowledgeRevision

        relation = KnowledgeRevision.objects.select_related("publication").get(
            pk=selected.identifier
        )
        record["metadata"] = {key: opened[key] for key in ("number", "state", "kind", "title")}
        if "source" in opened:
            underlying = research._source_resource(
                opened["source"], relation.snapshot["source_sha256"]
            )
            permissions(case, actor, provider, underlying, False)
            record["metadata"]["source"] = {
                key: opened["source"][key] for key in SOURCE_FIELDS if key in opened["source"]
            }
        if "material" in opened:
            underlying, _ = research._transcript(
                case, actor, provider, str(relation.transcript_id), "READ_TEXT"
            )
            permissions(case, actor, provider, underlying, False)
            record["content"] = {
                key: opened["material"][key] for key in ("text", "start_ms", "end_ms")
            }
        # Approved source relation is preserved; no unpublished review history,
        # actor identities, private notes or case original are exported.
        record["relationships"] = [
            {
                "type": "approved-knowledge-source",
                "kind": underlying.kind,
                "identifier": underlying.identifier,
                "version_sha256": underlying.sha256,
            },
            {
                "type": "published-edition",
                "identifier": str(relation.publication_id),
                "version_sha256": relation.publication.content_sha256,
                "number": relation.publication.number,
            },
        ]
    else:
        media_type = opened["media_type"]
        if media_type not in EXTENSIONS:
            raise cases.CaseConflict("export_media_type_unsupported")
        raw = bytes(opened["raw"]) if include_files else None
        if raw is not None and sha256(raw).hexdigest() != selected.sha256:
            raise cases.CaseConflict("export_media_changed")
        record["metadata"] = {
            "media_type": media_type,
            "bytes": len(raw) if raw is not None else opened["size"],
            "original_file_included": include_files,
        }
        if include_files:
            checked(raw.decode("utf-8", errors="ignore"))
            # Deliberately omit original filenames and storage locations.
            path = f"media/{ordinal:04d}.{EXTENSIONS[media_type]}"
            files[path] = raw
            record["files"] = [{"path": path, "sha256": selected.sha256, "bytes": len(raw)}]
    checked(record)
    permissions(case, actor, provider, selected, include_files)
    return record, files


def media_metadata(case, actor, provider, selected):
    row = next(
        (r for r in research._media_rows(case) if research._media_resource(r) == selected), None
    )
    if row is None:
        raise cases.CaseConflict("export_media_changed")
    require(actor, provider, case, "DISCOVER", selected)
    return row


def unavailable_permission(case, actor, provider, selected, include_files):
    """A missing byte object may be an explicit failed slot, never an access grant."""
    selected = resource(selected)
    if selected.kind not in MEDIA or include_files is not True:
        raise cases.CaseConflict("export_resource_unavailable")
    permissions(case, actor, provider, selected, include_files)
    media_metadata(case, actor, provider, selected)
    require(actor, provider, case, "READ_MEDIA", selected)


def pin(selected, record):
    return {"resource": asdict(resource(selected)), "record_sha256": digest(record)}
