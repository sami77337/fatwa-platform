"""Metadata observations, never scholarly verification or a source export."""

from collections import Counter

from apps.reference.records import InvalidCatalog, PreparedCatalog, prepare_catalog


def audit_citation_metadata(prepared: PreparedCatalog, *, max_samples: int = 10) -> dict:
    """Summarize ambiguity in a validated source, preserving lexical part labels.

    Shared locators and repeated titles are observations, not corruption. Use the
    edition plus heading identity for a citation; a printed page is not unique.
    Only bounded heading IDs are emitted, never titles or full locator tables.
    """
    if type(max_samples) is not int or not 1 <= max_samples <= 100:
        raise ValueError("max_samples must be 1..100")
    checked = prepare_catalog(prepared.spec, prepared.records)
    if checked.checksum != prepared.checksum:
        raise InvalidCatalog("Prepared source checksum changed before citation audit")
    rows = checked.records
    printed = Counter((r.source_part, r.source_page_number) for r in rows)
    pages = Counter(r.source_page_id for r in rows)
    titles = Counter(r.title_original for r in rows)
    conditions = {
        "SHARED_PRINTED_LOCATOR": lambda r: printed[r.source_part, r.source_page_number] > 1,
        "SHARED_SOURCE_PAGE_ID": lambda r: pages[r.source_page_id] > 1,
        "REPEATED_ORIGINAL_TITLE": lambda r: titles[r.title_original] > 1,
        "NAMED_PART": lambda r: not (r.source_part.isascii() and r.source_part.isdecimal()),
        "LEXICAL_NUMERIC_PART": lambda r: (
            r.source_part.isascii() and r.source_part.isdecimal()
            and r.source_part != str(int(r.source_part))
        ),
        "ENTRY_NUMBER_ABSENT": lambda r: r.source_entry_number is None,
    }
    observations = {}
    for code, condition in conditions.items():
        ids = sorted(r.source_row_id for r in rows if condition(r))
        observations[code] = {
            "heading_count": len(ids), "sample_heading_ids": ids[:max_samples],
            "samples_omitted": max(0, len(ids) - max_samples),
        }
    return {
        "kind": "SOURCE_BOOK_TOC_NOT_FATWAS",
        "scope": "VALIDATED_SOURCE_METADATA_ONLY",
        "scholarly_content_verification": "NOT_PERFORMED",
        "printed_page_content_verification": "NOT_PERFORMED",
        "database_match": "NOT_ASSERTED_BY_THIS_SUMMARY",
        "mapped_checksum": checked.checksum,
        "source_archive_sha256": checked.spec.source_archive_sha256,
        "source_input_sha256": checked.spec.source_input_sha256,
        "input_name": checked.spec.input_name,
        "edition_key": checked.spec.edition_key,
        "heading_count": len(rows),
        "unique_printed_locators": len(printed),
        "unique_source_page_ids": len(pages),
        "observations": observations,
        "observation_semantics": "INFORMATIONAL_NOT_INTEGRITY_FAILURES",
        "citation_identity_fields": [
            "source_namespace", "source_book_id", "edition_key",
            "source_archive_sha256", "source_input_sha256", "source_row_id", "source_id",
        ],
    }
