from django.urls import path

from apps.casework_web.requester_workspace_urls import urlpatterns as workspace_patterns

from . import views

urlpatterns = [
    path("casework/status/", views.requester, name="requester_access_review"),
    path("casework/staff/", views.staff, name="staff_access_review"),
    *workspace_patterns,
]
