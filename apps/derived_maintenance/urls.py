from django.urls import path

from . import views

urlpatterns = [
    path("casework/staff/derived-data/", views.workspace, name="derived-staff"),
    path("casework/operations/derived-data/", views.workspace, name="derived-operational"),
]
