"""Combined training desk only; no public URL configuration imports this."""
from django.urls import path
from apps.delivery_queue import author_http
from . import views
urlpatterns = [
    path('review/author/approval/', views.author_page),
    path('review/author/approval/login/', author_http.author_login),
    path('review/author/approval/request.json', author_http.export_request),
    path('review/author/approval/review/', views.author_submit),
    path('review/author/approval/receipt/', views.author_stage),
    path('review/author/approval/desk.css', author_http.stylesheet),
    path('review/mufti/login/', views.mufti_login),
    path('review/mufti/logout/', views.mufti_logout),
    path('review/mufti/decisions/', views.mufti_page),
    path('review/mufti/decisions/record/', views.mufti_decide),
    path('review/mufti/decisions/decision.json', views.decision_export),
]
