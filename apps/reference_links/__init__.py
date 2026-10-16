"""Read-only, exact-identity TOC evidence resolution; no scholarly rulings."""

from .bridge import (
    BridgeConfig, EditionMap, HeadingMap, PointerResult, RowResult,
    SourceIdentity, resolve_prepared_pointers,
)

from .resolution import (
    CatalogReadError,
    Heading,
    Outcome,
    ReadOnlyCatalog,
    Resolution,
    SnapshotCatalog,
    render_citation,
    resolve,
    resolve_intake,
)

__all__ = [
    "BridgeConfig", "EditionMap", "HeadingMap", "PointerResult", "RowResult",
    "SourceIdentity", "resolve_prepared_pointers",
    "CatalogReadError",
    "Heading",
    "Outcome",
    "ReadOnlyCatalog",
    "Resolution",
    "SnapshotCatalog",
    "render_citation",
    "resolve",
    "resolve_intake",
]
