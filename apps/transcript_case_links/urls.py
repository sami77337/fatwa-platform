from django.urls import path

from config.campaign_urls import urlpatterns as campaign

from .views import staff

urlpatterns = [
    path("casework/staff/", staff, name="casework_staff"),
    *(p for p in campaign if p.name != "casework_staff"),
]
