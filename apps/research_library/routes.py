from django.urls import path

from . import offline, views

app_name = "research_library"
urlpatterns = [
    path("", views.index, name="index"),
    path("offline/", offline.asset, name="offline"),
    path("offline/manifest.webmanifest", offline.manifest, name="offline_manifest"),
    path("offline/catalog/", offline.catalog, name="offline_catalog"),
    path("offline/package/", offline.archive, name="offline_archive"),
    path("offline/packets/<uuid:version_id>/", offline.download_packet, name="offline_packet"),
    path("offline/<str:name>", offline.asset, name="offline_asset"),
    path("<uuid:public_id>/<int:number>/", views.detail, name="detail"),
    path("<uuid:public_id>/<int:number>/file/", views.file, name="file"),
]
