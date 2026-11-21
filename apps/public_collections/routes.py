from django.urls import path

from . import views

app_name = "public_collections"
urlpatterns = [
    path("", views.index, name="index"),
    path("items/<uuid:public_id>/", views.detail, name="detail"),
    path("collections.css", views.stylesheet, name="styles"),
]
