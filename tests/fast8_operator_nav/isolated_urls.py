from django.urls import include, path

urlpatterns = [path("operator", include("apps.fast8_operator_nav.urls"))]
