from django.urls import path

from . import views

urlpatterns = [
    path("casework/", views.intake, name="casework_intake"),
    path("casework/status/", views.status, name="casework_status"),
    path("casework/followup/", views.followup, name="casework_followup"),
    path("casework/staff/login/", views.staff_login, name="casework_login"),
    path("casework/staff/logout/", views.staff_logout, name="casework_logout"),
    path("casework/staff/", views.staff, name="casework_staff"),
    path("casework/casework.css", views.stylesheet, name="casework_css"),
]
