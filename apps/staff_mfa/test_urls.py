from django.urls import include, path

urlpatterns = [path("", include("apps.staff_mfa.urls")), path("", include("config.campaign_urls"))]
