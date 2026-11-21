"""Executable route/field contract; only documented reads are admitted."""

from .services import SCHEMA


def contract():
    return {
        "schema": SCHEMA, "version": 1, "read_only": True,
        "base_path": "/library-preview/api/v1/materials/", "methods": ["GET", "HEAD"],
        "endpoints": {
            "": {"purpose": "Latest currently released version per material; bounded metadata search", "query": {
                "q": "Optional text, maximum120 characters; searches public title/work/creator/description",
                "kind": "Optional exact BOOK/DOCUMENT/IMAGE/AUDIO/VIDEO kind",
                "page": "ASCII integer1..1000, default1", "limit": "ASCII integer1..20, default10"}},
            "{material_id}/versions/{number}/": {"purpose": "Exact released historical version and readable reference", "query": {}},
            "{material_id}/versions/{number}/original/": {"purpose": "Exact original bytes, requiring current PUBLIC_CONTENT and DOWNLOAD uses", "query": {}},
            "docs/": {"purpose": "Native reference explorer using the same query contract"},
            "schema.json": {"purpose": "This versioned contract", "query": {}},
        },
        "identity": {"material_id": "Stable public UUID; never a private case identifier", "version": "Immutable positive version number", "version_sha256": "Exact current version digest"},
        "material_fields": ["material_id", "version", "version_sha256", "kind", "title", "description", "language", "reference", "recorded_text", "file", "links"],
        "file_fields": ["media_type", "size", "sha256"],
        "errors": {"400": "invalid_request", "403": "request_denied", "404": "unavailable", "405": "method_not_allowed"},
        "availability": "Every read rechecks exact review/release, source bytes, current actor and use authority. Metadata permission does not grant content or download. Pagination totals contain currently visible records only.",
        "response_policy": "private,no-store; HEAD has no body; unknown or duplicate parameters fail; no credential-bearing URLs or anonymous write/approve/publish/private-case endpoint",
        "deployment": "Disabled by default. Current implementation is the loopback-only synthetic development composition; production exposure and service-auth contracts remain separate.",
    }
