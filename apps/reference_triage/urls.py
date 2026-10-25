from django.urls import path

from .views import investigation

app_name = "reference_triage"
urlpatterns = [
    path("", investigation, name="index"),
    path("/<slug:key>", investigation, name="detail"),
]
