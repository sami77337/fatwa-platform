"""Separate training URLconf. Never included in the public application."""
from django.urls import path
from . import author_http
urlpatterns = [
    path('review/author/approval/', author_http.author_page),
    path('review/author/approval/login/', author_http.author_login),
    path('review/author/approval/request.json', author_http.export_request),
    path('review/author/approval/receipt/', author_http.import_response),
    path('review/author/approval/desk.css', author_http.stylesheet),
]
