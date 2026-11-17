from django.urls import path

from apps.casework_web.urls import urlpatterns as casework_patterns

from .views import inbox

urlpatterns = [
    path("casework/staff/", inbox, name="casework_staff"),
    *(pattern for pattern in casework_patterns if pattern.name != "casework_staff"),
]
