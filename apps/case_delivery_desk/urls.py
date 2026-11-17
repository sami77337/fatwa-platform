from django.urls import path

from apps.casework_web.views import staff_logout

from . import views

urlpatterns = [
    path("casework/staff/login/", views.login, name="delivery_desk_login"),
    path("casework/staff/logout/", staff_logout, name="delivery_desk_logout"),
    path("casework/staff/", views.desk, name="delivery_desk"),
    path("casework/casework.css", views.stylesheet, name="delivery_desk_css"),
]
