"""Public reference metadata only; no scholarly ruling or private-case entities."""
from django.db import models
from django.db.models import F, Q


class ReferenceWork(models.Model):
    source_namespace = models.CharField(max_length=40)
    source_book_id = models.CharField(max_length=80)
    title_original = models.CharField(max_length=500)
    madhhab = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["source_namespace", "source_book_id"], name="ref_work_source_unique"
        )]


class ReferenceEdition(models.Model):
    work = models.ForeignKey(ReferenceWork, on_delete=models.PROTECT, related_name="editions")
    edition_key = models.CharField(max_length=100)
    title = models.CharField(max_length=500)
    publisher = models.CharField(max_length=500)
    source_archive_sha256 = models.CharField(max_length=64)
    source_input_sha256 = models.CharField(max_length=64)
    input_name = models.CharField(max_length=255)
    ingest_checksum = models.CharField(max_length=64)
    heading_count = models.PositiveIntegerField()
    root_count = models.PositiveIntegerField()
    max_depth = models.PositiveSmallIntegerField()
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["work", "edition_key"], name="ref_edition_unique"),
            models.CheckConstraint(condition=Q(heading_count__gte=1), name="ref_edition_nonempty"),
            models.CheckConstraint(condition=Q(root_count__gte=1), name="ref_edition_roots"),
            models.CheckConstraint(
                condition=Q(max_depth__gte=1, max_depth__lte=5), name="ref_edition_depth"
            ),
        ]


class ReferenceHeading(models.Model):
    edition = models.ForeignKey(ReferenceEdition, on_delete=models.PROTECT, related_name="headings")
    source_id = models.CharField(max_length=100)
    source_row_id = models.PositiveBigIntegerField()
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    source_order = models.PositiveIntegerField()
    position = models.PositiveIntegerField()
    depth = models.PositiveSmallIntegerField()
    source_page_id = models.PositiveBigIntegerField()
    source_part = models.CharField(max_length=100)
    source_page_number = models.PositiveIntegerField()
    source_entry_number = models.PositiveIntegerField(null=True, blank=True)
    title_original = models.CharField(max_length=500)
    title_normalized = models.CharField(max_length=2000)

    class Meta:
        ordering = ["source_order", "source_row_id"]
        indexes = [
            models.Index(fields=["edition", "parent", "position"], name="ref_children_idx"),
            models.Index(fields=["edition", "title_original"], name="ref_exact_title_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["edition", "source_id"], name="ref_source_id_unique"),
            models.UniqueConstraint(fields=["edition", "source_row_id"], name="ref_row_id_unique"),
            models.UniqueConstraint(fields=["edition", "source_order"], name="ref_order_unique"),
            models.UniqueConstraint(
                fields=["edition", "parent", "position"], nulls_distinct=False,
                name="ref_sibling_position_unique",
            ),
            models.CheckConstraint(condition=Q(depth__gte=1, depth__lte=5), name="ref_heading_depth"),
            models.CheckConstraint(condition=Q(source_row_id__gte=1), name="ref_row_positive"),
            models.CheckConstraint(condition=Q(source_order__gte=1), name="ref_order_positive"),
            models.CheckConstraint(condition=Q(position__gte=1), name="ref_position_positive"),
            models.CheckConstraint(condition=Q(source_page_id__gte=1), name="ref_page_id_positive"),
            models.CheckConstraint(condition=Q(source_page_number__gte=1), name="ref_page_positive"),
            models.CheckConstraint(
                condition=Q(source_entry_number__isnull=True) | Q(source_entry_number__gte=1),
                name="ref_entry_positive",
            ),
            models.CheckConstraint(condition=~Q(title_original=""), name="ref_title_nonempty"),
            models.CheckConstraint(condition=~Q(source_part=""), name="ref_part_nonempty"),
            models.CheckConstraint(condition=~Q(parent_id=F("id")), name="ref_no_self_parent"),
            models.CheckConstraint(
                condition=(Q(parent__isnull=True, depth=1) | Q(parent__isnull=False, depth__gte=2)),
                name="ref_root_depth",
            ),
        ]
