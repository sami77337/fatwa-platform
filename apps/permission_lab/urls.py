from django.urls import path

from . import views

app_name = "permission_lab"
urlpatterns = [
    path("", views.inspect, name="index"),
    path("/style.css", views.stylesheet, name="style"),
]
