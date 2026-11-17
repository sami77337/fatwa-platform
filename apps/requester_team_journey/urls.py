from django.urls import path

from apps.casework_web import requester_intake
from apps.casework_web import views as existing
from apps.requester_access_review.views import requester
from apps.team_workspace.views import stylesheet

from .views import staff

# Exact existing paths: no guard, cookie scope or public URL registration changes.
urlpatterns = [
    path("casework/", requester_intake.intake, name="casework_intake"),
    path("casework/status/", requester, name="casework_status"),
    path("casework/followup/", existing.followup, name="casework_followup"),
    path("casework/staff/login/", existing.staff_login, name="casework_login"),
    path("casework/staff/logout/", existing.staff_logout, name="casework_logout"),
    path("casework/staff/", staff, name="casework_staff"),
    path("casework/casework.css", stylesheet, name="casework_css"),
]
