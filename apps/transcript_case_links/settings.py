"""Isolated additive integration profile; shared campaign files remain untouched."""

from copy import deepcopy
from pathlib import Path

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.transcript_case_links.apps.TranscriptCaseLinksConfig"]  # noqa: F405
ROOT_URLCONF = "apps.transcript_case_links.urls"
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 262144
DATA_UPLOAD_MAX_NUMBER_FILES = 1
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]["DIRS"].insert(0, Path(__file__).parent / "templates")
