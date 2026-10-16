from django.urls import path

from apps.public_site import views as public_views
from apps.reference import views

urlpatterns = [
    path("", public_views.home, name="home"),
    path("help", public_views.help_page, name="public_help"),
    path("fiqh", views.catalog, name="catalog"),
    path("fiqh/nodes/<int:ident>", views.catalog, name="heading"),
    path("fiqh/nodes/<int:ident>/children", views.branch, name="branch"),
    path("healthz", views.health, name="health"),
    path("readyz", views.ready, name="ready"),
    path("api/v1/status", views.status, name="status"),
    path("api/v1/fiqh/books", views.api_books, name="api_books"),
    path("api/v1/fiqh/roots", views.api_roots, name="api_roots"),
    path("api/v1/fiqh/search", views.api_search, name="api_search"),
    path("api/v1/fiqh/nodes/<int:ident>", views.api_node, name="api_node"),
    path("api/v1/fiqh/nodes/<int:ident>/children", views.api_children, name="api_children"),
    path("assets/<path:asset>", views.public_asset, name="public_asset"),
]
