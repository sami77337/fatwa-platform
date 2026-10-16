"""Read-only, exact-identity TOC evidence resolution; no scholarly rulings."""

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
