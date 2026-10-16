"""Catalog-only settings. No admin, auth, sessions, or private product apps."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]
if os.environ.get("FATWA_PRODUCTION", "0") != "0":
    raise ImproperlyConfigured("Production is disabled: NOT_DEPLOYED / GATES_HOLD")

DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.public_site.apps.PublicSiteConfig",
    "apps.reference.apps.ReferenceConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.PublicReadOnlyMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("PGDATABASE", "fatwa_reference_dev"),
    "USER": os.environ.get("PGUSER", "fatwa_reference_dev"),
    "PASSWORD": os.environ.get("PGPASSWORD", ""),
    "HOST": os.environ.get("PGHOST", "127.0.0.1"),
    "PORT": os.environ.get("PGPORT", "5432"),
    "CONN_MAX_AGE": 0,
    "OPTIONS": {
        "connect_timeout": 5,
        "options": "-c statement_timeout=3000 -c lock_timeout=3000",
    },
    "TEST": {"NAME": os.environ.get("PGTESTDATABASE", "test_fatwa_reference_dev")},
}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Amman"
USE_I18N = True
USE_TZ = True
APPEND_SLASH = False
STATIC_URL = "/assets/"
DATA_UPLOAD_MAX_MEMORY_SIZE = 8192
DATA_UPLOAD_MAX_NUMBER_FIELDS = 16
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = []
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
# A statement of scope, never a set of activatable permission switches.
CATALOG_READ_ONLY = True
SENSITIVE_OPERATIONS_ENABLED = False
