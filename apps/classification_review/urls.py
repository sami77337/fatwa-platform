"""Isolated dispatcher; campaign wiring is exclusively the integrator's responsibility."""

from django.urls import path

from apps.knowledge_links.urls import staff as knowledge_staff
from apps.knowledge_links.urls import urlpatterns as knowledge_patterns

from .views import ACTIONS, workspace


def staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    return knowledge_staff(request)


urlpatterns = [path("casework/staff/", staff), *knowledge_patterns]
