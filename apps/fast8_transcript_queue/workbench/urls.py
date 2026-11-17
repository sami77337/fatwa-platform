from django.urls import path

from . import views

urlpatterns = [
    path("transcripts/", views.index),
    path("transcripts/review/", views.update),
    path("transcripts/example/", views.example),
    path("transcripts/workbench.css", views.stylesheet),
]
