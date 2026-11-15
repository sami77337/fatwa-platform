"""Default-off loopback author approval intake; no sender or signing service."""
import os
from .delivery_queue_test import *

ROOT_URLCONF = 'apps.delivery_queue.author_urls'
ALLOWED_HOSTS = ['127.0.0.1', '[::1]']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'apps.delivery_queue.author_http.AuthorDeskGuard',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
FATWA_AUTHOR_APPROVAL_ENABLED = os.environ.get('FATWA_AUTHOR_APPROVAL_ENABLED') == '1'
FATWA_AUTHOR_APPROVAL_DIRECTORY = os.environ.get('FATWA_AUTHOR_APPROVAL_DIRECTORY')
FATWA_AUTHOR_APPROVAL_CASES = tuple(value for value in os.environ.get('FATWA_AUTHOR_APPROVAL_CASES', '').split(',') if value)
FATWA_AUTHOR_APPROVAL_MAX_CHARS = 280
# Configure a reviewed Ed25519ApprovalVerifier in server code. No browser value,
# arbitrary import path, permissive callback or embedded signing key is accepted.
FATWA_AUTHOR_APPROVAL_VERIFIER = None
CSRF_COOKIE_NAME = 'fatwa_training_desk_csrf'
CSRF_COOKIE_PATH = '/review/'
CSRF_COOKIE_SECURE = False  # Loopback HTTP only; not an Internet deployment.
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
SECURE_REFERRER_POLICY = 'same-origin'
DATA_UPLOAD_MAX_MEMORY_SIZE = 65536
DATA_UPLOAD_MAX_NUMBER_FIELDS = 8
