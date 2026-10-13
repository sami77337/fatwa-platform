"""Loopback-only development. An ephemeral signing key is never stored."""
import secrets

from .base import *

SECRET_KEY = SECRET_KEY or secrets.token_urlsafe(48)
