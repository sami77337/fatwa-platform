"""Source-preserving, synthetic-only Arabic text quality diagnostics."""

from .service import compare_texts, inspect_revision, inspect_text

__all__ = ["compare_texts", "inspect_revision", "inspect_text"]
