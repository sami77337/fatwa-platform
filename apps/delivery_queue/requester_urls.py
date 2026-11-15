"""Explicit synthetic-only URL configuration, absent from the public app."""
from django.urls import path
from . import requester_http

urlpatterns = [
    path("requester/tracking/", requester_http.portal, name="synthetic_requester_tracking"),
    path("requester/tracking/tracking.css", requester_http.stylesheet, name="synthetic_requester_tracking_css"),
]
