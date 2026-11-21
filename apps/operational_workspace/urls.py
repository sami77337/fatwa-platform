from django.urls import path

from . import views

urlpatterns = [
    path("casework/operations/", views.workspace, name="operational_workspace"),
    path("casework/operations/login/", views.login, name="operational_login"),
    path("casework/operations/logout/", views.logout, name="operational_logout"),
]
