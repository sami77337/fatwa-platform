"""Service boundary checks with fake source services; never opens a DB connection."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        # Setup model registry only; no migration, query, or source import.
        django.setup()

    def test_exact_service_reads(self):
        from apps.reference import services
        from apps.reference_links.django_adapter import DjangoCatalog

        edition = SimpleNamespace(
            pk=2,
            work=SimpleNamespace(
                title_original="مرجع", source_namespace="synthetic", source_book_id="fixture"
            ),
            source_input_sha256="b" * 64,
            edition_key="synthetic-edition",
            source_archive_sha256="a" * 64,
        )
        heading = SimpleNamespace(
            source_row_id=8, title_original="باب", source_part="1", source_page_number=20
        )
        with (
            patch.object(services, "resolve_edition", return_value=edition) as editions,
            patch.object(services, "node", return_value=heading) as nodes,
            patch.object(services, "heading_path", return_value=[{"title": "باب"}]),
        ):
            rows = DjangoCatalog().lookup(2, 8)
        editions.assert_called_once_with(2)
        nodes.assert_called_once_with(edition, 8)
        self.assertEqual(rows[0].path, ("باب",))
        self.assertEqual(rows[0].edition_id, 2)
        self.assertEqual(rows[0].edition_key, "synthetic-edition")
        self.assertEqual(rows[0].source_archive_sha256, "a" * 64)

    def test_missing_and_unavailable(self):
        from apps.reference import services
        from apps.reference_links import CatalogReadError
        from apps.reference_links.django_adapter import DjangoCatalog

        with patch.object(services, "resolve_edition", side_effect=services.HeadingNotFound):
            self.assertEqual(DjangoCatalog().lookup(1, 1), ())
        with patch.object(services, "resolve_edition", side_effect=services.CatalogUnavailable):
            with self.assertRaises(CatalogReadError):
                DjangoCatalog().lookup(1, 1)
