"""Development-only, source-pinned fiqh heading ingestion (no database access)."""

from .ingest import (
    ImportResult,
    IngestError,
    Manifest,
    ValidationError,
    ingest,
    load_manifest,
    write_export,
)

__all__ = [
    "ImportResult", "IngestError", "Manifest", "ValidationError",
    "ingest", "load_manifest", "write_export",
]
