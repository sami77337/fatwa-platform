from django.urls import path

from . import views

urlpatterns = [
    path("library-preview/teaching/", views.catalog, name="teaching_catalog"),
    path(
        "library-preview/teaching/scholars/<uuid:public_id>/",
        views.scholar,
        name="teaching_scholar",
    ),
    path(
        "library-preview/teaching/lessons/<uuid:public_id>/", views.lesson, name="teaching_lesson"
    ),
    path(
        "library-preview/teaching/lessons/<uuid:public_id>/<int:number>/media/",
        views.audio,
        name="teaching_audio",
    ),
    path("library-preview/teaching/series/<uuid:public_id>/", views.series, name="teaching_series"),
    path(
        "library-preview/teaching/series/<uuid:series_id>/lessons/<uuid:public_id>/",
        views.lesson,
        name="teaching_series_lesson",
    ),
]
