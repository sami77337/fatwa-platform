"""Explicit synthetic-only development registration; public/base settings unchanged."""
import copy
import os
from .development import *
from apps.intake_workflow.contracts import DATABASE_ROLE, SOURCE_CONFIG_ID, SYNTHETIC_SCOPE

INSTALLED_APPS = [*INSTALLED_APPS, 'apps.intake_workflow.apps.IntakeWorkflowConfig']
DATABASES = copy.deepcopy(DATABASES)
DATABASES['default'].update(
    NAME=os.environ.get('PGDATABASE', 'wave7_synthetic_unconfigured'),
    USER=os.environ.get('PGUSER', DATABASE_ROLE), HOST=os.environ.get('PGHOST', '127.0.0.1'),
    PORT=os.environ.get('PGPORT', '1'),
    TEST={'NAME': os.environ.get('PGTESTDATABASE', 'test_wave7_synthetic_unconfigured')})
WAVE7_SCOPE = SYNTHETIC_SCOPE
WAVE7_SOURCE_CONFIG_ID = SOURCE_CONFIG_ID
WAVE7_BASE_DATABASE_NAME = DATABASES['default']['NAME']
WAVE7_TEST_DATABASE_NAME = DATABASES['default']['TEST']['NAME']
