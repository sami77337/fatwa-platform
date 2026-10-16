"""Run A2 tests without a server, migrations, fixtures, or database connections.

Usage: python -B tests/integration/api/run_isolated.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import django
    from django.conf import settings

    if settings.configured:
        raise RuntimeError("Use a fresh Python process for the A2 isolated runner")
    settings.configure(
        SECRET_KEY="a2-isolated-test-key",
        DEBUG=False,
        ALLOWED_HOSTS=["testserver"],
        ROOT_URLCONF="config.urls",
        INSTALLED_APPS=[
            "django.contrib.staticfiles",
            "django_htmx",
            "apps.reference.apps.ReferenceConfig",
        ],
        MIDDLEWARE=["config.middleware.PublicReadOnlyMiddleware"],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "a2_cursor_fake_never_connect",
                "USER": "unused",
                "HOST": "invalid.invalid",
            }
        },
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [ROOT / "templates"],
                "APP_DIRS": True,
            }
        ],
        STATIC_URL="/assets/",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
    )
    with patch(
        "django.db.backends.postgresql.base.DatabaseWrapper.get_new_connection",
        side_effect=AssertionError("A2 isolated tests must never open a database connection"),
    ):
        django.setup()
        from django.db import connections

        # Compilation uses PostgreSQL features; no SELECT version() is permitted.
        connections["default"].__dict__["pg_version"] = 180006
        suite = unittest.defaultTestLoader.discover(
            str(Path(__file__).parent), "test_*.py", top_level_dir=str(ROOT)
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
