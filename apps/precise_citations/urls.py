from django.urls import path

from . import editor

urlpatterns = [
    path("sources/<uuid:anchor_id>/", editor.source, name="precise-source"),
    path(
        "sources/<uuid:anchor_id>/file/", editor.source, {"raw": True}, name="precise-source-file"
    ),
    path("print/<uuid:set_id>/", editor.export, name="precise-print"),
    path("export/<uuid:set_id>/", editor.export, {"format": "json"}, name="precise-export"),
]
