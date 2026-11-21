"""Disposable composition profile for the recording and exact-citation readers."""

from .settings import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.precise_citations"]))  # noqa: F405
