from django.urls import path

from . import views

urlpatterns = [
    path("casework/staff/record-lifecycle/", views.workspace, name="suppression-staff"),
    path("casework/operations/record-lifecycle/", views.workspace, name="suppression-operational"),
]
