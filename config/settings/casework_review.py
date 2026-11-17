"""Explicit local synthetic journey. Never registered in public/production settings."""
import os

from .casework_test import *

DEBUG = False
ROOT_URLCONF = "apps.casework_web.urls"
ALLOWED_HOSTS = ["127.0.0.1", "[::1]"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.casework_web.guard.CaseworkGuard",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
FATWA_CASEWORK_WEB_ENABLED = os.environ.get("FATWA_CASEWORK_WEB_ENABLED") == "1"
# Explicit reviewed server objects are required. Browser forms cannot configure them.
FATWA_CASEWORK_IDENTITY_PROVIDER = None
FATWA_CASEWORK_RECOVERY_RESOLVER = None
CSRF_COOKIE_NAME = "fatwa_casework_csrf"
CSRF_COOKIE_PATH = "/casework/"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = False  # This profile is restricted to loopback HTTP.
SECURE_REFERRER_POLICY = "same-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = 262144
DATA_UPLOAD_MAX_NUMBER_FIELDS = 12
