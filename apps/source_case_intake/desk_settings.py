"""Explicit local source desk profile; flags remain closed until opted in."""

from .settings import *  # noqa: F403

ROOT_URLCONF = "apps.source_case_intake.urls"
FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED = False
