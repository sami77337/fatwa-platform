"""Isolated HTTP profile for one loopback-only synthetic reading desk."""

from config.settings.development import *  # noqa: F403

ROOT_URLCONF = "apps.editorial_workbench.reviewer_desk"
ALLOWED_HOSTS = ["127.0.0.1"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.editorial_workbench.reviewer_desk.DeskGuard",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
CSRF_COOKIE_NAME = "fatwa_training_desk_csrf"
CSRF_COOKIE_PATH = "/review/"
CSRF_COOKIE_SECURE = False  # This profile binds to literal HTTP loopback.
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_HTTPONLY = True
