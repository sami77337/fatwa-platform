"""Explicit isolated PostgreSQL synthetic queue tests only."""
from .wave7_test import *

INSTALLED_APPS = [*INSTALLED_APPS, "apps.delivery_queue.apps.DeliveryQueueConfig"]
