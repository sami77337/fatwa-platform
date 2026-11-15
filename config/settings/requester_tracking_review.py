"""Disabled-by-default loopback-only requester tracking view."""
import os
from .delivery_queue_test import *

ROOT_URLCONF = "apps.delivery_queue.requester_urls"
ALLOWED_HOSTS = ["127.0.0.1", "[::1]"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.delivery_queue.requester_http.RequesterTrackingGuard",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
FATWA_REQUESTER_TRACKING_ENABLED = os.environ.get("FATWA_REQUESTER_TRACKING_ENABLED") == "1"
CSRF_COOKIE_NAME = "fatwa_requester_tracking_csrf"
CSRF_COOKIE_PATH = "/requester/"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = False  # Loopback HTTP fixture only.
DATA_UPLOAD_MAX_MEMORY_SIZE = 4096
DATA_UPLOAD_MAX_NUMBER_FIELDS = 4
SECURE_REFERRER_POLICY = "no-referrer"
