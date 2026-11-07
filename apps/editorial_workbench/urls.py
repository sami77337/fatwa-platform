"""One namespaced include; the Wave7 profile inherits the base routes."""

from django.urls import path

from . import views
from .persisted import stored_audit
from .source_review import source_journal_review, source_review

app_name = "editorial_workbench"
urlpatterns = [
    path("", views.workbench, name="index"),
    path("/style.css", views.stylesheet, name="style"),
    path("/workflow-audit", stored_audit, name="stored"),
    path("/intake-7/source-review", source_review, name="source_review"),
    path("/intake-7/source-review/journal", source_journal_review, name="source_journal"),
    path("/<slug:key>", views.workbench, name="detail"),
]
