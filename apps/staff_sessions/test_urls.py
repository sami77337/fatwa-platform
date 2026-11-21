from django.urls import include, path

urlpatterns = [
    path("casework/sessions/", include("apps.staff_sessions.urls")),
    path("casework/operations/sessions/", include("apps.staff_sessions.urls")),
    path("", include("apps.operational_workspace.urls")),
    path("", include("apps.casework_web.urls")),
]
