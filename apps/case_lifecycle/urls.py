from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import dispatch

urlpatterns = [
    path("casework/staff/", dispatch, name="casework_staff"),
    *(
        pattern
        for pattern in campaign_patterns
        if getattr(pattern, "name", None) != "casework_staff"
    ),
]
