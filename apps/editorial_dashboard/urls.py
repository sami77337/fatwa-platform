from django.urls import path

from . import views

app_name = "editorial_dashboard"
urlpatterns = [
    path("", views.dashboard, name="index"),
    path("/style.css", views.stylesheet, name="style"),
]
