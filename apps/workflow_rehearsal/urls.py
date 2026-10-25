from django.urls import path

from . import views

app_name = "workflow_rehearsal"
urlpatterns = [
    path("", views.desk, name="index"),
    path("/style.css", views.stylesheet, name="style"),
    path("/<slug:key>", views.desk, name="detail"),
]
