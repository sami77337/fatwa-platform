"""One namespaced include; the Wave7 profile inherits the base routes."""

from django.urls import path

from . import views
from .persisted import stored_audit

app_name = "editorial_workbench"
urlpatterns = [
    path("", views.workbench, name="index"),
    path("/style.css", views.stylesheet, name="style"),
    path("/workflow-audit", stored_audit, name="stored"),
    path("/<slug:key>", views.workbench, name="detail"),
]
