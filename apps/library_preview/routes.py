"""Include this module in the integrated URLconf; no shared-config import cycle."""

from django.urls import path

from . import views

app_name = "library_preview"
urlpatterns = [
    path("", views.index, name="index"),
    path("preview.css", views.stylesheet, name="style"),
    path("editions/<uuid:publication_id>/", views.detail, name="detail"),
    path("editions/<uuid:publication_id>/references/<int:position>/", views.source, name="source"),
]
