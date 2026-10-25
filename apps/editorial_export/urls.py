from django.urls import path

from . import views

app_name = "editorial_export"

urlpatterns = [
    path("", views.index, name="index"),
    path("/<str:filename>", views.download, name="download"),
]
