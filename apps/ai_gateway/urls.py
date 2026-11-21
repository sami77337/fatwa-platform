from django.urls import path

from . import panel

urlpatterns = [path("", panel.workspace), path("panel.mjs", panel.script)]
