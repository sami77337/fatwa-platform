"""Coordinator may mount explicitly; this lane changes no shared URL config."""

from django.urls import path

from .views import inspect

app_name = "fast9_case_policy_join"
urlpatterns = [
    path("select", inspect, name="select"),
    path("evaluate", inspect, {"evaluate": True}, name="evaluate"),
]
