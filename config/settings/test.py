"""Tests require real PostgreSQL; there is deliberately no SQLite fallback."""
from .development import *

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "[::1]"]

# FileResponse.close() emits request_finished; retain class-level TestCase
# transactions across streaming responses in the disposable test database.
DATABASES = {**DATABASES, "default": {**DATABASES["default"], "CONN_MAX_AGE": 60}}
