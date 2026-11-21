"""Connect released lesson metadata to separately released current recordings."""

from contextlib import ExitStack, contextmanager

from apps.library_preview import services as preview
from apps.library_preview.navigation import teaching_catalog_url


@contextmanager
def knowledge_projection():
    """Reuse the teaching reader's retained knowledge source, without new grants.

    An unavailable optional teaching configuration leaves ordinary metadata usable.
    Once admitted, its final checks remain outside rendering: late changes must
    discard the response, never fall back to an already assembled page.
    """
    with ExitStack() as stack:
        current = None
        if teaching_catalog_url():
            from .services import public_projection

            try:
                current = stack.enter_context(public_projection())
            except preview.PreviewUnavailable:
                pass
        if current is not None:
            snapshot = current.guard.source.pk
        else:
            from apps.public_knowledge.public import projection

            snapshot = stack.enter_context(projection())
        yield snapshot, current


def lesson_links(snapshot, current, series_id):
    if current is None:
        return []
    identifiers = {key for key, row in snapshot.lessons.items() if row["id"] == str(series_id)}
    return [
        {"url": dto["url"], "title": dto["title"], "version": dto["number"]}
        for row, dto in current.rows.values()
        if row.item.kind == "LESSON" and str(row.lesson_metadata_id) in identifiers
    ]
