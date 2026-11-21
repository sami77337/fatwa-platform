from django.urls import path

from . import views

urlpatterns = [
    path("library-preview/reading/saved/", views.saved, name="public_reader_saved"),
    path(
        "library-preview/reading/tools.js",
        views.asset,
        {"name": "tools.js"},
        name="public_reader_script",
    ),
    path(
        "library-preview/reading/tools.css",
        views.asset,
        {"name": "tools.css"},
        name="public_reader_style",
    ),
    path("library-preview/reading/<uuid:publication_id>/", views.reader, name="public_reader"),
    path(
        "library-preview/reading/<uuid:publication_id>/save-reference/",
        views.descriptor,
        name="public_reader_reference",
    ),
    path(
        "library-preview/reading/<uuid:publication_id>/share-link/",
        views.descriptor,
        {"action": "SHARE_LINK"},
        name="public_reader_share",
    ),
    path(
        "library-preview/reading/<uuid:publication_id>/print-permission/",
        views.descriptor,
        {"action": "PRINT"},
        name="public_reader_print_permission",
    ),
    path(
        "library-preview/reading/<uuid:publication_id>/print/",
        views.print_view,
        name="public_reader_print",
    ),
    path(
        "library-preview/reading/<uuid:publication_id>/download/",
        views.download,
        name="public_reader_download",
    ),
]
