"""Tests require real PostgreSQL; there is deliberately no SQLite fallback."""
from .development import *

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "[::1]"]

