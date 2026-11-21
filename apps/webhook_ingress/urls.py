"""Development-only webhook callback, outside staff/requester surfaces."""

from django.urls import path

from .views import callback

urlpatterns = [
    path("casework/webhooks/<uuid:account_id>/", callback, name="source_webhook_callback"),
]
