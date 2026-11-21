from django.urls import path

from .views import asset

urlpatterns = [
    path("casework/staff/pwa/<str:name>", asset, name="staff_pwa_asset"),
]
