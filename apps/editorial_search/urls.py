from django.urls import path

from . import views

app_name = "editorial_search"
urlpatterns = [
    path("", views.search, name="index"),
    path("/style.css", views.stylesheet, name="style"),
]
