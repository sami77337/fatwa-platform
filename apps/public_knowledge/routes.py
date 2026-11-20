"""All anonymous routes retain the existing local preview security boundary."""

from django.urls import path

from . import views

app_name = "public_knowledge"
urlpatterns = [
    path("", views.index, name="index"),
    path("scholars/<uuid:series_id>/", views.scholar, name="scholar"),
    path("topics/<uuid:series_id>/", views.topic, name="topic"),
    path("lessons/<uuid:series_id>/", views.lesson, name="lesson"),
    path(
        "publications/<uuid:publication_id>/<str:language>/",
        views.publication_page,
        name="publication",
    ),
    path("sitemap.xml", views.sitemap, name="sitemap"),
]
