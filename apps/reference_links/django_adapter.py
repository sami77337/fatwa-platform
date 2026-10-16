"""Optional Django service adapter. Instantiation performs no I/O; lookup only reads."""

from .resolution import CatalogReadError, Heading


class DjangoCatalog:
    def lookup(self, edition_id: int, source_row_id: int) -> tuple[Heading, ...]:
        from django.db import DatabaseError

        from apps.reference import services

        try:
            edition = services.resolve_edition(edition_id)
            heading = services.node(edition, source_row_id)
            path = services.heading_path(edition, heading)
            return (
                Heading(
                    edition_id=edition.pk,
                    source_row_id=heading.source_row_id,
                    work_title=edition.work.title_original,
                    heading_title=heading.title_original,
                    printed_part=heading.source_part,
                    printed_page=heading.source_page_number,
                    path=tuple(entry["title"] for entry in path),
                    source_namespace=edition.work.source_namespace,
                    source_book_id=edition.work.source_book_id,
                    source_input_sha256=edition.source_input_sha256,
                ),
            )
        except services.HeadingNotFound:
            return ()
        except (services.CatalogUnavailable, DatabaseError) as error:
            raise CatalogReadError("Catalog read unavailable") from error
