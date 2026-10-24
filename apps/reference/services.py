"""Bounded ORM reads and explicit public representations of source metadata."""

from dataclasses import dataclass

from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from .models import ReferenceEdition, ReferenceHeading
from .normalization import normalize_title
from .query import MAX_SOURCE_ID, InvalidQuery, Page, validate_search, validate_search_filters

KIND = "SOURCE_BOOK_TOC_NOT_FATWAS"


class HeadingNotFound(LookupError):
    pass


class EditionNotFound(HeadingNotFound):
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
            raise EditionNotFound("Unknown edition")
        return edition
    candidates = list(editions.order_by("pk")[:2])
    if len(candidates) > 1:
        raise InvalidQuery("Select an edition explicitly")
    return candidates[0] if candidates else None


def _headings(edition: ReferenceEdition) -> QuerySet:
    # Keep child aggregation off the outer query: COUNT/paging must operate on
    # headings, not on a grouped join of every matching heading and its children.
    child_counts = (
        ReferenceHeading.objects.filter(edition=edition, parent_id=OuterRef("pk"))
        .order_by()
        .values("parent_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return ReferenceHeading.objects.filter(edition=edition).annotate(
        parent_source_row_id=F("parent__source_row_id"),
        children_count=Coalesce(Subquery(child_counts), 0),
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
    items = (
        [heading_data(row) for row in queryset[page.offset : page.offset + page.limit]]
        if page.offset < total
        else []
    )
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


def root_page(
    edition: ReferenceEdition | None,
    page: Page,
    anchor_id: int | None = None,
) -> CatalogPage:
    """Locate a breadcrumb root in its bounded page, preserving source order."""
    if anchor_id is not None:
        if page.offset:
            raise InvalidQuery("Anchor and offset are mutually exclusive")
        anchor = node(edition, anchor_id)
        if anchor.edition_id != edition.pk or anchor.parent_id is not None or anchor.depth != 1:
            raise HeadingNotFound("Anchor is not a root in this edition")
        preceding = (
            ReferenceHeading.objects.filter(edition=edition, parent__isnull=True)
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
    return roots(edition, page)


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
    *,
    depth: int | None = None,
    has_children: bool | None = None,
) -> CatalogPage:
    validate_search(text, mode)
    validate_search_filters(depth, has_children)
    value = normalize_title(text) if mode == "normalized" else text
    # Scope validity is independent of whether the search text has any matches.
    root = None
    if root_id is not None:
        root = node(edition, root_id)
        if root.parent_id is not None or root.depth != 1:
            raise InvalidQuery("Search scope must be a root")
    # An explicitly selected filter is useful without search text. A nonblank
    # query reduced to nothing by normalization (marks/tatweel) still matches
    # nothing, and an unfiltered blank search keeps its existing empty contract.
    filter_only = not text.strip() and (
        root_id is not None or depth is not None or has_children is not None
    )
    if edition is None or (not value.strip() and not filter_only):
        return CatalogPage([], 0, page.limit, page.offset, None)
    queryset = _headings(edition)
    if depth is not None:
        queryset = queryset.filter(depth=depth)
    if has_children is not None:
        child_exists = Exists(
            ReferenceHeading.objects.filter(edition=edition, parent_id=OuterRef("pk"))
        )
        queryset = queryset.filter(child_exists if has_children else ~child_exists)
    if root is not None:
        # Fixed-depth ORM joins, with source identity checked at every ancestor.
        # Use database PKs internally; source row IDs may repeat across editions.
        scope = Q(pk=root.pk)
        for depth in range(1, 5):
            ancestors = {"parent__" * level + "edition": edition for level in range(1, depth + 1)}
            ancestors.update(
                {"parent__" * level + "depth": depth + 1 - level for level in range(1, depth)}
            )
            scope |= Q(**{"depth": depth + 1, "parent__" * depth + "pk": root.pk, **ancestors})
        queryset = queryset.filter(scope)
    if mode == "exact" and not filter_only:
        queryset = queryset.filter(title_original=value)
    elif not filter_only:
        field = "title_normalized" if mode == "normalized" else "title_original"
        for token in dict.fromkeys(value.split()):
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


# Wave7 is deliberately separate from the immutable reference-catalog API above.
# Model imports happen only after explicit enablement and owned-schema validation.
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from django.apps import apps as django_apps
from django.conf import settings
from django.db import DatabaseError

from apps.intake_workflow import contracts as workflow_contracts
from apps.intake_workflow.source_slices import SourceSlice

WORKFLOW_MAX_SEARCH_ROWS = workflow_contracts.MAX_ITEMS
WORKFLOW_MAX_SEARCH_BYTES = workflow_contracts.MAX_INPUT_BYTES


class WorkflowReadsDisabled(RuntimeError):
    pass


class WorkflowReadUnavailable(RuntimeError):
    pass


class WorkflowItemNotFound(LookupError):
    pass


class WorkflowSearchScopeRequired(InvalidQuery):
    pass


@dataclass(frozen=True, slots=True)
class WorkflowBatchRead:
    id: str
    idempotency_key: str
    created_at: datetime
    item_count: int


@dataclass(frozen=True, slots=True)
class WorkflowItemRead:
    id: str
    batch_id: str
    row_ordinal: int
    external_id: str | None
    question_original: str | None
    intake_status: str
    review_status: str
    reference_count: int
    verified_reference_count: int


@dataclass(frozen=True, slots=True)
class WorkflowReferenceRead:
    id: str
    reference_ordinal: int
    source: SourceSlice
    reference_status: str
    citation_text: str | None
    verification_results: dict


@dataclass(frozen=True, slots=True)
class WorkflowItemDetail:
    item: WorkflowItemRead
    source: SourceSlice
    references: tuple[WorkflowReferenceRead, ...]
    prepared_clip_url: str | None
    validation_results: dict

    def as_dict(self) -> dict:
        # No decoded source numerics: exact token text and byte ranges only.
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkflowPage:
    items: tuple[WorkflowBatchRead | WorkflowItemRead, ...]
    total: int
    limit: int
    offset: int
    next_offset: int | None

    def as_dict(self) -> dict:
        return {"items": [asdict(row) for row in self.items], "total": self.total,
                "count": self.total, "limit": self.limit, "offset": self.offset,
                "next_offset": self.next_offset}


def _workflow_reads_enabled() -> bool:
    import os
    return (getattr(settings, 'WAVE7_READS_ENABLED', False) is True
            and os.environ.get('FATWA_WAVE7_SYNTHETIC_READS') == '1'
            and django_apps.is_installed('apps.intake_workflow'))


def _require_workflow_read(*, synthetic_fixtures_only=False, using='default') -> None:
    if synthetic_fixtures_only is not True:
        raise InvalidQuery('Explicit synthetic acknowledgement required')
    if not _workflow_reads_enabled():
        raise WorkflowReadsDisabled()
    from apps.intake_workflow.guards import require_synthetic_write, SyntheticWriteDenied
    try:
        # This shared guard only checks configuration, ownership and schema.
        # No atomic(), write permit, initializer or fixture operation on reads.
        require_synthetic_write(synthetic_fixtures_only=True, using=using)
    except (SyntheticWriteDenied, DatabaseError):
        raise WorkflowReadUnavailable() from None


def _workflow_uuid(value) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or len(value) != 36:
        raise InvalidQuery('Expected a canonical workflow UUID')
    try:
        result = UUID(value)
    except ValueError:
        raise InvalidQuery('Expected a canonical workflow UUID') from None
    if str(result) != value.lower():
        raise InvalidQuery('Expected a canonical workflow UUID')
    return result


def _workflow_filters(text, mode, intake_status, review_status, page, batch_id=None):
    if not isinstance(text, str) or not isinstance(mode, str):
        raise InvalidQuery('Invalid workflow query')
    validate_search(text, mode)
    try:
        text.encode('utf-8')
    except UnicodeError:
        raise InvalidQuery('Invalid workflow query') from None
    for value, enum in ((intake_status, workflow_contracts.IntakeStatus),
                        (review_status, workflow_contracts.ReviewStatus)):
        if value is not None and (not isinstance(value, str) or value not in enum):
            raise InvalidQuery('Invalid workflow status')
    if not isinstance(page, Page):
        raise InvalidQuery('Invalid workflow page')
    return _workflow_uuid(batch_id) if batch_id is not None else None


def _workflow_batches_queryset(using):
    from apps.intake_workflow.models import IntakeBatch
    return IntakeBatch.objects.using(using).filter(
        scope=workflow_contracts.SYNTHETIC_SCOPE,
        source_config_id=workflow_contracts.SOURCE_CONFIG_ID,
        contract_version=workflow_contracts.CONTRACT_VERSION)


def _workflow_items_queryset(using):
    from apps.intake_workflow.models import IntakeItem
    return IntakeItem.objects.using(using).filter(
        batch__scope=workflow_contracts.SYNTHETIC_SCOPE,
        batch__source_config_id=workflow_contracts.SOURCE_CONFIG_ID,
        batch__contract_version=workflow_contracts.CONTRACT_VERSION)


def _workflow_matches(queryset, text, mode, intake_status, review_status):
    if intake_status is not None:
        queryset = queryset.filter(intake_status=intake_status)
    if review_status is not None:
        queryset = queryset.filter(review_status=review_status)
    if not text.strip():
        return queryset  # Explicit browse/filter-only semantics, including blocked rows.
    if mode == 'exact':
        return queryset.filter(question_original=text)
    if mode == 'literal':
        for token in dict.fromkeys(text.split()):
            queryset = queryset.filter(question_original__contains=token)
        return queryset
    query = normalize_title(text)
    if not query:
        return queryset.none()
    tokens = tuple(dict.fromkeys(query.split()))
    found, size = [], 0
    candidates = queryset.exclude(question_original__isnull=True).order_by(
        'batch__created_at', 'batch_id', 'row_ordinal', 'id').values_list('id', 'question_original')
    # Streaming avoids loading an unbounded cross-batch corpus or repeating batch
    # payloads. No approximate SQL normalization or derived source mutation.
    for number, (ident, original) in enumerate(candidates[:WORKFLOW_MAX_SEARCH_ROWS + 1].iterator(chunk_size=1), 1):
        size += len(original.encode('utf-8'))
        if number > WORKFLOW_MAX_SEARCH_ROWS or size > WORKFLOW_MAX_SEARCH_BYTES:
            raise WorkflowSearchScopeRequired('Select a smaller batch/status search scope')
        normalized = normalize_title(original)
        if all(token in normalized for token in tokens):
            found.append(ident)
    return queryset.filter(pk__in=found)


def _workflow_item_projection(row) -> WorkflowItemRead:
    return WorkflowItemRead(str(row.pk), str(row.batch_id), row.row_ordinal,
        row.external_id, row.question_original, row.intake_status, row.review_status,
        row._reference_count, row._verified_count)


def _workflow_annotated_items(queryset):
    return queryset.annotate(_reference_count=Count('references'),
        _verified_count=Count('references', filter=Q(references__reference_status='VERIFIED')))


def _workflow_page(queryset, page, project):
    total = queryset.count()
    rows = tuple(project(row) for row in queryset[page.offset:page.offset+page.limit]) if page.offset < total else ()
    return WorkflowPage(rows, total, page.limit, page.offset, page.next_offset(total))


def workflow_items(*, batch_id=None, text='', mode='normalized', intake_status=None,
                   review_status=None, page=Page(20), synthetic_fixtures_only=False,
                   using='default') -> WorkflowPage:
    batch_id = _workflow_filters(text, mode, intake_status, review_status, page, batch_id)
    _require_workflow_read(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    try:
        queryset = _workflow_items_queryset(using)
        if batch_id is not None:
            if not _workflow_batches_queryset(using).filter(pk=batch_id).exists():
                raise WorkflowItemNotFound()
            queryset = queryset.filter(batch_id=batch_id)
        queryset = _workflow_matches(queryset, text, mode, intake_status, review_status)
        return _workflow_page(_workflow_annotated_items(queryset).only(
            'id', 'batch_id', 'row_ordinal', 'external_id', 'question_original',
            'intake_status', 'review_status').order_by(
            'batch__created_at', 'batch_id', 'row_ordinal', 'id'), page, _workflow_item_projection)
    except DatabaseError:
        raise WorkflowReadUnavailable() from None


def workflow_batches(*, text='', mode='normalized', intake_status=None, review_status=None,
                     page=Page(20), synthetic_fixtures_only=False, using='default') -> WorkflowPage:
    _workflow_filters(text, mode, intake_status, review_status, page)
    _require_workflow_read(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    try:
        batches = _workflow_batches_queryset(using)
        if text.strip() or intake_status is not None or review_status is not None:
            items = _workflow_matches(_workflow_items_queryset(using), text, mode, intake_status, review_status)
            batches = batches.filter(Exists(items.filter(batch_id=OuterRef('pk'))))
        batches = batches.annotate(_item_count=Count('items')).only(
            'id', 'idempotency_key', 'created_at').order_by('created_at', 'id')
        return _workflow_page(batches, page, lambda row: WorkflowBatchRead(
            str(row.pk), row.idempotency_key, row.created_at, row._item_count))
    except DatabaseError:
        raise WorkflowReadUnavailable() from None


def workflow_item(item_id, *, batch_id=None, synthetic_fixtures_only=False,
                  using='default') -> WorkflowItemDetail:
    item_id = _workflow_uuid(item_id)
    batch_id = _workflow_uuid(batch_id) if batch_id is not None else None
    _require_workflow_read(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    try:
        queryset = _workflow_items_queryset(using).filter(pk=item_id)
        if batch_id is not None:
            queryset = queryset.filter(batch_id=batch_id)
        row = _workflow_annotated_items(queryset).select_related('batch').first()
        if row is None:
            raise WorkflowItemNotFound()
        parsed = workflow_contracts.parse_synthetic_payload(bytes(row.batch.original_payload),
            synthetic_fixtures_only=True)
        source = SourceSlice(row.source_byte_start, row.source_byte_end, row.original_row)
        if not 1 <= row.row_ordinal <= len(parsed.item_sources) or source != parsed.item_sources[row.row_ordinal-1]:
            raise WorkflowReadUnavailable()
        source_row = parsed.items[row.row_ordinal-1]
        clip = source_row.get('prepared_clip_url') if isinstance(source_row, dict) else None
        pointers = parsed.reference_sources[row.row_ordinal-1]
        stored_refs = list(row.references.using(using).order_by('reference_ordinal')[:workflow_contracts.MAX_REFERENCES_PER_ITEM+1])
        if len(stored_refs) > workflow_contracts.MAX_REFERENCES_PER_ITEM:
            raise WorkflowReadUnavailable()
        references = []
        for ref in stored_refs:
            pointer = SourceSlice(ref.source_byte_start, ref.source_byte_end, ref.original_pointer)
            if not 1 <= ref.reference_ordinal <= len(pointers) or pointer != pointers[ref.reference_ordinal-1]:
                raise WorkflowReadUnavailable()
            citation = None
            if ref.reference_status == 'VERIFIED':
                workflow_contracts.validate_verified_identity(ref.verified_identity)
                citation = ref.citation_text or None
            references.append(WorkflowReferenceRead(str(ref.pk), ref.reference_ordinal, pointer,
                ref.reference_status, citation, ref.verification_results))
        return WorkflowItemDetail(_workflow_item_projection(row), source, tuple(references),
            clip if isinstance(clip, str) else None, row.validation_results)
    except (DatabaseError, workflow_contracts.ContractError):
        raise WorkflowReadUnavailable() from None
