"""Guarded disposable Wave7 tests only. No public/default settings registration."""
from .wave7_development import *

ALLOWED_HOSTS = [*ALLOWED_HOSTS, 'testserver']
TEST_RUNNER = 'tests.wave7_foundation.runner.Wave7TestRunner'
