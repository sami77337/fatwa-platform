import sys

import django
from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database)
def catalog_database_check(app_configs, **kwargs):
    errors = []
    for alias in kwargs.get("databases") or []:
        connection = connections[alias]
        if connection.vendor != "postgresql":
            errors.append(Error("Catalog requires PostgreSQL 17/18.", id="reference.E001"))
        elif not 170000 <= connection.pg_version < 190000:
            errors.append(Error("Use PostgreSQL 18 preferred or 17 fallback.", id="reference.E002"))
    return errors


@register()
def selected_runtime_check(app_configs, **kwargs):
    errors = []
    if sys.version_info[:2] != (3, 13):
        errors.append(Error("The selected development runtime is Python 3.13.", id="reference.E003"))
    if django.VERSION[:2] != (5, 2):
        errors.append(Error("The selected framework is Django 5.2 LTS.", id="reference.E004"))
    return errors
