"""HTTP-only audit query parsing and deterministic navigation over reader DTOs.

UUIDs, search/status validity and combined pagination bounds remain owned by the
existing review reader. These helpers perform no reads or domain transitions.
"""

from urllib.parse import urlencode

from django.http import QueryDict

from apps.intake_workflow import contracts as c
from apps.intake_workflow.review import ReviewWorklist

from .views import _positive_query


def parse_audit_query(query: QueryDict) -> tuple[str, dict[str, str | int | None]]:
    """Reject ambiguous HTTP input and return the format plus reader arguments."""
    allowed = {'batch', 'row', 'q', 'mode', 'intake_status', 'review_status',
               'page', 'page_size', 'format'}
    if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
        raise c.ContractError('review: invalid_query')
    output_format = query.get('format', 'html')
    if output_format not in {'html', 'json'}:
        raise c.ContractError('review: invalid_format')
    return output_format, {
        'batch_id': query.get('batch'), 'row_id': query.get('row'),
        'q': query.get('q', ''), 'mode': query.get('mode', 'normalized'),
        'intake_status': query.get('intake_status', ''),
        'review_status': query.get('review_status', ''),
        'page': _positive_query(query.get('page', '1'), 10000),
        'page_size': _positive_query(query.get('page_size', '20'), 50),
    }


def _url(base: str, params: dict[str, str | int], *, page: int | None = None,
         row_id: str | None = None, records: bool = False) -> str:
    values = dict(params)
    if page is not None:
        values['page'] = page
    if row_id is not None:
        values['row'] = row_id
    return base + '?' + urlencode(values) + ('#records' if records else '')


def build_audit_navigation(stored: ReviewWorklist, base: str, persisted_base: str) -> dict:
    """Build links from the returned worklist, never from stale request values.

    Parameter order is fixed. Page/list links intentionally omit the selected
    row; detail links retain it even when it is outside the filtered page.
    Call after the existing audit projection has checked the stored contract.
    """
    params = dict(q=stored.q, mode=stored.mode, intake_status=stored.intake_status,
                  review_status=stored.review_status, page=stored.page, page_size=stored.page_size)
    if stored.batch_id is not None:
        params['batch'] = str(stored.batch_id)
    selected_id = str(stored.row.id) if stored.row is not None else None
    return {
        'base_url': base,
        'list_url': _url(base, params, records=True),
        'selected_url': _url(base, params, row_id=selected_id),
        'persisted_url': _url(persisted_base, params, row_id=selected_id),
        'selected_on_page': stored.row is not None and any(row.id == stored.row.id for row in stored.rows),
        'display_rows': tuple({'item': row, 'detail_url': _url(base, params, row_id=str(row.id))}
                              for row in stored.rows),
        'pagination_fields': tuple((key, value) for key, value in params.items() if key != 'page'),
        'first_url': _url(base, params, page=1, records=True) if stored.page > 1 else None,
        'previous_url': _url(base, params, page=stored.page - 1, records=True) if stored.page > 1 else None,
        'next_url': _url(base, params, page=stored.page + 1, records=True) if stored.page < stored.page_count else None,
        'last_url': _url(base, params, page=stored.page_count, records=True) if stored.page < stored.page_count else None,
    }
