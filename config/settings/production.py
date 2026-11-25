"""Production boot is denied until a separately accepted deployment mission."""
from django.core.exceptions import ImproperlyConfigured

raise ImproperlyConfigured("Production is disabled: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED")
