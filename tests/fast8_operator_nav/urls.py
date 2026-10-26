from django.urls import include, path

from config.urls import urlpatterns as project_urls

urlpatterns = [
    path("operator", include("apps.fast8_operator_nav.urls")),
    # Keep the isolated lane prefix without registering its namespace twice.
    *[route for route in project_urls if getattr(route, "namespace", None) != "fast8_operator_nav"],
]
