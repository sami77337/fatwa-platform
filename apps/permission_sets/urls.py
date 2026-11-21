from django.urls import path

from . import views

urlpatterns = [
    path("casework/staff/permissions/", views.workspace, name="staff_permissions"),
    path("casework/operations/permissions/", views.workspace, name="operational_permissions"),
]
