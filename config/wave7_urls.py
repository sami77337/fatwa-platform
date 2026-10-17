"""Available Wave7 read-only service; selected only by the separate Wave7 profile."""
from django.urls import path

from apps.editorial_demo import views as editorial_views
from config.urls import urlpatterns as legacy_patterns


urlpatterns = [
    path('dev/editorial-preview/persisted', editorial_views.persisted_review,
         name='wave7_editorial_review'),
    *legacy_patterns,
]
