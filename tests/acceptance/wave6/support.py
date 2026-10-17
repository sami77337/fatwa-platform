"""Disposable fixture builder. Never imports an archive or touches owner data."""
import os

from django.conf import settings


NAMESPACE = "wave6-e6-synthetic"
TITLE = "كِتَابُ الطَّهَارَةِ"


def require_disposable_database():
    database = settings.DATABASES["default"]
    if (
        os.environ.get("E6_SYNTHETIC_ONLY") != "1"
        or database["ENGINE"] != "django.db.backends.postgresql"
        or not database["NAME"].startswith("e6_synthetic")
        or not database.get("TEST", {}).get("NAME", "").startswith("test_e6_synthetic")
        or database["HOST"] != "127.0.0.1"
    ):
        raise RuntimeError("E6 requires explicit acknowledgement and isolated loopback e6_synthetic/test_e6_synthetic PostgreSQL names")


def seed_catalog():
    # Called only inside Django's newly created disposable test database.
    from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
    from apps.reference.normalization import normalize_title

    if not settings.DATABASES["default"]["NAME"].startswith("test_e6_synthetic"):
        raise RuntimeError("E6 fixture writes require a disposable TEST database")
    if ReferenceEdition.objects.exists():
        raise RuntimeError("E6 refuses to seed an occupied catalog")
    work = ReferenceWork.objects.create(
        source_namespace=NAMESPACE, source_book_id="e6-fabricated",
        title_original="مرجع اصطناعي لاختبار المتصفح", madhhab="اختبار فقط",
    )
    edition = ReferenceEdition.objects.create(
        work=work, edition_key="e6-synthetic-only", title="طبعة اصطناعية داخلية",
        publisher="ناشر اصطناعي", source_archive_sha256="a" * 64,
        source_input_sha256="b" * 64, ingest_checksum="c" * 64,
        input_name="generated-e6-not-owner-source", heading_count=47, root_count=2, max_depth=2,
    )

    def heading(ident, title, parent=None, position=1):
        return ReferenceHeading.objects.create(
            edition=edition, source_id=f"e6-{ident}", source_row_id=ident,
            source_order=ident, position=position, depth=2 if parent else 1,
            parent=parent, source_page_id=ident, source_part="الأول",
            source_page_number=ident, title_original=title, title_normalized=normalize_title(title),
        )

    root = heading(1, TITLE)
    heading(2, "كتاب الصلاة الاصطناعي", position=2)
    for index in range(45):
        heading(index + 3, f"باب اصطناعي للطهارة {index + 1:02d}", root, index + 1)
    return edition
