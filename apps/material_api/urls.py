from django.urls import path

from . import views

app_name = "material_api"
urlpatterns = [
    path("", views.index, name="index"),
    path("docs/", views.docs, name="docs"),
    path("schema.json", views.schema, name="schema"),
    path("<uuid:public_id>/versions/<int:number>/", views.detail, name="detail"),
    path("<uuid:public_id>/versions/<int:number>/original/", views.original, name="original"),
]
