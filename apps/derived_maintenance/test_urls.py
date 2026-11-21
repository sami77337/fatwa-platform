# The native app URLs are added here only until the integrator registers them
# in the actual campaign URL configuration. No middleware guard is bypassed.
from config.campaign_urls import urlpatterns as campaign_urls

from .urls import urlpatterns as derived_urls

urlpatterns = [*derived_urls, *campaign_urls]
