from django.urls import path

from .views import research

app_name = "research_bridge"
urlpatterns = [
    path("", research, name="index"),
    path("/<slug:key>", research, name="detail"),
]
