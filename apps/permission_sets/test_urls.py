from django.urls import include, path

urlpatterns = [
    path("", include("apps.permission_sets.urls")),
    path("", include("config.campaign_urls")),
]
