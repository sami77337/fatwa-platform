"""Isolated, disabled development composition; no scanner or policy is selected."""

from apps.data_privacy.settings import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.upload_security"]))  # noqa: F405
FATWA_UPLOAD_SECURITY_ENABLED = False
FATWA_UPLOAD_SCAN_POLICY = None
FATWA_UPLOAD_SCANNER = None
FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC = False
