"""Test-only Wave7 route proposal; production/shared URLconf is untouched."""
from django.urls import path
from apps.editorial_demo.views import persisted_review
from config.urls import urlpatterns as legacy_patterns

urlpatterns = [path('dev/editorial-preview/persisted', persisted_review, name='wave7_editorial_review'), *legacy_patterns]
