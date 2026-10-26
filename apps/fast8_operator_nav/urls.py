from django.urls import path

from . import views

app_name = "fast8_operator_nav"
urlpatterns = [
    path("", views.navigation, name="index"),
    path("/style.css", views.stylesheet, name="style"),
    path("/<slug:key>", views.navigation, name="detail"),
]
