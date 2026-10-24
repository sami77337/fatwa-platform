from django.urls import path

from . import views

app_name = "editorial_queue"
urlpatterns = [
    path("", views.queue, name="index"),
    path("/style.css", views.stylesheet, name="style"),
    path("/<slug:key>", views.queue, name="detail"),
]
