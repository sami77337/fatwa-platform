"""Explicit loopback-only synthetic PostgreSQL report profile. Default off."""
import os
from .delivery_queue_test import *

ROOT_URLCONF = 'apps.delivery_queue.review_urls'
ALLOWED_HOSTS = ['127.0.0.1', '[::1]']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'apps.delivery_queue.review_http.LoopbackReviewGuard',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
FATWA_PG_DELIVERY_REPORTS_ENABLED = os.environ.get('FATWA_PG_DELIVERY_REPORTS') == '1'
FATWA_PG_DELIVERY_OPERATOR_CASES = {
    'synthetic-operator': tuple(value for value in os.environ.get('FATWA_PG_DELIVERY_CASES', '').split(',') if value)
}
CSRF_COOKIE_NAME = 'fatwa_training_desk_csrf'
CSRF_COOKIE_PATH = '/review/'
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = 'same-origin'
DATA_UPLOAD_MAX_MEMORY_SIZE = 2048
