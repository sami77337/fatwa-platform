from django.urls import path

from . import views

urlpatterns = [
    path("casework/staff/mfa/", views.page, {"surface": "CASEWORK"}, name="staff_mfa"),
    path("casework/operations/mfa/", views.page, {"surface": "OPERATIONS"}, name="operations_mfa"),
]
