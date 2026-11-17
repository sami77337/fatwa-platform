"""Opt-in loopback profile, no database, no shared casework registration."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = os.environ.get("FATWA_TRANSCRIPT_SECRET", "")
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "[::1]"]
ROOT_URLCONF = "apps.fast8_transcript_queue.workbench.urls"
INSTALLED_APPS = []
DATABASES = {}
MIDDLEWARE = [
    "apps.fast8_transcript_queue.workbench.views.LocalGuard",
    "django.middleware.csrf.CsrfViewMiddleware",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": False,
    }
]
FATWA_TRANSCRIPT_WORKBENCH_ENABLED = os.environ.get("FATWA_TRANSCRIPT_WORKBENCH") == "1"
DATA_UPLOAD_MAX_MEMORY_SIZE = 4_000_000
FILE_UPLOAD_MAX_MEMORY_SIZE = 4_000_000
DATA_UPLOAD_MAX_NUMBER_FIELDS = 12
DATA_UPLOAD_MAX_NUMBER_FILES = 1
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
CSRF_COOKIE_NAME = "fatwa_transcript_csrf"
CSRF_COOKIE_PATH = "/transcripts/"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = False
USE_I18N = False
USE_TZ = True
DEFAULT_CHARSET = "utf-8"
