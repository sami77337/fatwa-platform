from django.urls import path

from . import views

app_name = "editorial_search"
urlpatterns = [
    path("", views.search, name="index"),
    path("/style.css", views.stylesheet, name="style"),
    path("/references/<slug:key>/diagnostics/<int:ordinal>", views.reference, name="reference"),
    path(
        "/references/<slug:key>/revisions/<int:revision>/<int:ordinal>",
        views.reference,
        name="revision_reference",
    ),
]
