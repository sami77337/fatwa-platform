"""Bounded ORM reads and explicit public representations of source metadata."""

from dataclasses import dataclass

from django.db.models import Count, F, Q, QuerySet

from .models import ReferenceEdition, ReferenceHeading
from .normalization import normalize_title
from .query import MAX_SOURCE_ID, InvalidQuery, Page, validate_search

KIND = "SOURCE_BOOK_TOC_NOT_FATWAS"


class HeadingNotFound(LookupError):
    pass


class CatalogUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: list[dict]
    total: int
    limit: int
    offset: int
    next_offset: int | None

    def as_dict(self) -> dict:
        return {
            "items": self.items,
            "total": self.total,
            "count": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "next_offset": self.next_offset,
        }


def edition_data(edition: ReferenceEdition) -> dict:
    # Explicit whitelist: never serialize arbitrary model dictionaries or provenance files.
    return {
        "id": edition.pk,
        "edition_key": edition.edition_key,
        "title": edition.title,
        "publisher": edition.publisher,
        "heading_count": edition.heading_count,
        "root_count": edition.root_count,
        "max_depth": edition.max_depth,
        "source_archive_sha256": edition.source_archive_sha256,
        "source_input_sha256": edition.source_input_sha256,
        "work": {
            "source_namespace": edition.work.source_namespace,
            "source_book_id": edition.work.source_book_id,
            "title_original": edition.work.title_original,
            "madhhab": edition.work.madhhab,
        },
    }


def list_books(page: Page) -> CatalogPage:
    editions = ReferenceEdition.objects.select_related("work").order_by(
        "work__source_namespace", "work__source_book_id", "edition_key", "pk"
    )
    total = editions.count()
    items = [edition_data(edition) for edition in editions[page.offset : page.offset + page.limit]]
    return CatalogPage(
        items,
        total,
        page.limit,
        page.offset,
        page.next_offset(total),
    )


def resolve_edition(edition_id: int | None) -> ReferenceEdition | None:
    editions = ReferenceEdition.objects.select_related("work")
    if edition_id is not None:
        edition = editions.filter(pk=edition_id).first()
        if edition is None:
            raise HeadingNotFound("Unknown edition")
        return edition
    candidates = list(editions.order_by("pk")[:2])
    if len(candidates) > 1:
        raise InvalidQuery("Select an edition explicitly")
    return candidates[0] if candidates else None


def _headings(edition: ReferenceEdition) -> QuerySet:
    return ReferenceHeading.objects.filter(edition=edition).annotate(
        parent_source_row_id=F("parent__source_row_id"),
        children_count=Count("children", filter=Q(children__edition=edition)),
    )


def heading_data(heading: ReferenceHeading) -> dict:
    return {
        "id": heading.source_row_id,
        "source_id": heading.source_id,
        "parent_id": heading.parent_source_row_id,
        "title": heading.title_original,
        "depth": heading.depth,
        "position": heading.position,
        "source_order": heading.source_order,
        "children_count": heading.children_count,
        "part": heading.source_part,
        "page": heading.source_page_number,
        "page_id": heading.source_page_id,
        "source_entry_number": heading.source_entry_number,
    }


def _paginate(queryset: QuerySet, page: Page) -> CatalogPage:
    total = queryset.count()
    items = [heading_data(row) for row in queryset[page.offset : page.offset + page.limit]]
    return CatalogPage(
        items,
        total,
        page.limit,
        page.offset,
        page.next_offset(total),
    )


def roots(edition: ReferenceEdition | None, page: Page) -> CatalogPage:
    if edition is None:
        return CatalogPage([], 0, page.limit, page.offset, None)
    return _paginate(
        _headings(edition)
        .filter(parent__isnull=True)
        .order_by("position", "source_order", "source_row_id"),
        page,
    )


def node(edition: ReferenceEdition | None, ident: int) -> ReferenceHeading:
    if edition is None or not 1 <= ident <= MAX_SOURCE_ID:
        raise HeadingNotFound("Unknown heading")
    try:
        return _headings(edition).get(source_row_id=ident)
    except ReferenceHeading.DoesNotExist as error:
        raise HeadingNotFound("Unknown heading") from error


def _same_edition(edition: ReferenceEdition, heading: ReferenceHeading) -> None:
    if heading.edition_id != edition.pk:
        raise CatalogUnavailable("Invalid source hierarchy")


def children(edition: ReferenceEdition, heading: ReferenceHeading, page: Page) -> CatalogPage:
    _same_edition(edition, heading)
    return _paginate(
        _headings(edition)
        .filter(parent=heading)
        .order_by("position", "source_order", "source_row_id"),
        page,
    )


def heading_path(edition: ReferenceEdition, heading: ReferenceHeading) -> list[dict]:
    """Read at most four parents; a malformed path must never reveal another source."""
    result = []
    seen: set[int] = set()
    current = heading
    for _ in range(5):
        _same_edition(edition, current)
        if current.pk in seen or not 1 <= current.depth <= 5:
            raise CatalogUnavailable("Invalid source hierarchy")
        seen.add(current.pk)
        result.append(heading_data(current))
        if current.parent_id is None:
            if current.depth != 1 or current.parent_source_row_id is not None:
                raise CatalogUnavailable("Invalid source hierarchy")
            return result[::-1]
        if current.depth == 1 or current.parent_source_row_id is None:
            raise CatalogUnavailable("Invalid source hierarchy")
        # Do not issue an unnecessary sixth query for an invalid depth-five path.
        if len(result) == 5:
            break
        try:
            parent = node(edition, current.parent_source_row_id)
        except HeadingNotFound as error:
            raise CatalogUnavailable("Invalid source hierarchy") from error
        if parent.pk != current.parent_id or parent.depth != current.depth - 1:
            raise CatalogUnavailable("Invalid source hierarchy")
        current = parent
    raise CatalogUnavailable("Source hierarchy exceeds maximum depth")


def search(
    edition: ReferenceEdition | None,
    text: str,
    mode: str,
    page: Page,
    root_id: int | None = None,
) -> CatalogPage:
    validate_search(text, mode)
    value = normalize_title(text) if mode == "normalized" else text
    # Scope validity is independent of whether the search text has any matches.
    root = None
    if root_id is not None:
        root = node(edition, root_id)
        if root.parent_id is not None or root.depth != 1:
            raise InvalidQuery("Search scope must be a root")
    if edition is None or not value.strip():
        return CatalogPage([], 0, page.limit, page.offset, None)
    queryset = _headings(edition)
    if root is not None:
        # Fixed-depth ORM joins, with source identity checked at every ancestor.
        # Use database PKs internally; source row IDs may repeat across editions.
        scope = Q(pk=root.pk)
        for depth in range(1, 5):
            ancestors = {"parent__" * level + "edition": edition for level in range(1, depth + 1)}
            scope |= Q(**{"parent__" * depth + "pk": root.pk, **ancestors})
        queryset = queryset.filter(scope)
    if mode == "exact":
        queryset = queryset.filter(title_original=value)
    else:
        field = "title_normalized" if mode == "normalized" else "title_original"
        for token in value.split():
            # Django escapes LIKE wildcards and binds all values, including % and _.
            queryset = queryset.filter(**{f"{field}__contains": token})
    return _paginate(queryset.order_by("source_order", "source_row_id"), page)


def child_page(
    edition: ReferenceEdition,
    heading: ReferenceHeading,
    page: Page,
    anchor_id: int | None = None,
) -> CatalogPage:
    """Locate a breadcrumb child without guessing that sibling positions are contiguous."""
    _same_edition(edition, heading)
    if anchor_id is not None:
        if page.offset:
            raise InvalidQuery("Anchor and offset are mutually exclusive")
        anchor = node(edition, anchor_id)
        if anchor.parent_id != heading.pk:
            raise HeadingNotFound("Anchor is not a direct child")
        preceding = (
            ReferenceHeading.objects.filter(
                edition=edition,
                parent=heading,
            )
            .filter(
                Q(position__lt=anchor.position)
                | Q(position=anchor.position, source_order__lt=anchor.source_order)
                | Q(
                    position=anchor.position,
                    source_order=anchor.source_order,
                    source_row_id__lt=anchor.source_row_id,
                )
            )
            .count()
        )
        page = Page(page.limit, preceding // page.limit * page.limit)
    return children(edition, heading, page)
