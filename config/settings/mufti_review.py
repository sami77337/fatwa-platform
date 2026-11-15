"""Explicit loopback-only human review profile. Off until server configuration."""
import os
from .mufti_review_test import *

ROOT_URLCONF = 'apps.mufti_review.urls'
ALLOWED_HOSTS = ['127.0.0.1', '[::1]']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'apps.mufti_review.views.ReviewDeskGuard',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
FATWA_MUFTI_REVIEW_ENABLED = os.environ.get('FATWA_MUFTI_REVIEW_ENABLED') == '1'
FATWA_AUTHOR_APPROVAL_ENABLED = FATWA_MUFTI_REVIEW_ENABLED
FATWA_AUTHOR_APPROVAL_DIRECTORY = os.environ.get('FATWA_AUTHOR_APPROVAL_DIRECTORY')
FATWA_AUTHOR_APPROVAL_CASES = tuple(value for value in os.environ.get('FATWA_AUTHOR_APPROVAL_CASES', '').split(',') if value)
FATWA_AUTHOR_APPROVAL_MAX_CHARS = 280
# Supply reviewed server instances. No token, class import path, provider choice,
# signing key, issuer or trust map may be configured from a browser request.
FATWA_MUFTI_IDENTITY_PROVIDER = None
FATWA_AUTHOR_APPROVAL_VERIFIER = None
CSRF_COOKIE_NAME = 'fatwa_training_desk_csrf'
CSRF_COOKIE_PATH = '/review/'
CSRF_COOKIE_SECURE = False  # Strictly loopback HTTP; not Internet deployment.
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
SECURE_REFERRER_POLICY = 'same-origin'
DATA_UPLOAD_MAX_MEMORY_SIZE = 65536
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10
