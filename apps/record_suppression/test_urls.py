from django.urls import include, path

urlpatterns = [
    path("", include("apps.record_suppression.urls")),
    path("", include("config.campaign_urls")),
]
