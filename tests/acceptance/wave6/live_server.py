"""Shared E6 server class; browser and asset checks must use the same handler."""
from django.contrib.staticfiles.testing import StaticLiveServerTestCase


class SyntheticLiveServerTestCase(StaticLiveServerTestCase):
    host = "127.0.0.1"
