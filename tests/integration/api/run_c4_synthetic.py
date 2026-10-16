"""Execute synthetic ORM/API predicates in ephemeral SQLite memory only.

This is a supplemental logic test, NOT PostgreSQL acceptance or a settings fallback.
No migrations, existing database, source archive or environment credentials are used.
Usage: python -B tests/integration/api/run_c4_synthetic.py
"""

import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    import django
    from django.conf import settings

    settings.configure(
        SECRET_KEY="c4-synthetic-only",
        ALLOWED_HOSTS=["testserver"],
        ROOT_URLCONF="config.urls",
        INSTALLED_APPS=["apps.reference"],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
    )
    django.setup()
    from django.db import connection

    from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with connection.schema_editor() as editor:
            for model in [ReferenceWork, ReferenceEdition, ReferenceHeading]:
                editor.create_model(model)
    from tests.integration.api.synthetic_c4 import SyntheticFilterTests

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SyntheticFilterTests)
    )
    connection.close()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
