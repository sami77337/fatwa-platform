"""SYNTHETIC control-flow evidence only; no real AV or malware detection claim."""

from dataclasses import replace
from hashlib import sha256

from django.test import override_settings

from apps.case_attachments import tests as attachment_fixtures
from apps.casework import services as cases

from . import services
from .contract import Admission, FileScanner, ScannerSpec, ScanPolicy, ScanVerdict

RAW = b"SYNTHETIC original upload\r\nnot an antivirus fixture\n"


class SyntheticScanner(FileScanner):
    def __init__(self):
        self.current = ScannerSpec(
            "synthetic-upload-scanner",
            "SYNTHETIC-engine-v1",
            "SYNTHETIC-no-real-signatures",
            sha256(b"SYNTHETIC signatures").hexdigest(),
            sha256(b"SYNTHETIC scanner configuration").hexdigest(),
            "SYNTHETIC",
        )
        self.calls, self.changes, self.hook = [], {}, None

    @property
    def spec(self):
        return self.current

    def scan(self, request):
        self.calls.append(request)
        result = ScanVerdict("CLEAN", request.sha256, request.size, self.current, True, 1, 1)
        if self.hook:
            self.hook()
        return replace(result, **self.changes)


class ScanFixture:
    def setUp(self):
        super().setUp()
        self.receipt = attachment_fixtures.new_case()
        configure_scanner(self)
        self.admission = Admission(
            str(self.receipt["case_id"]),
            "casework-requester",
            self.receipt["requester_id"]
            if "requester_id" in self.receipt
            else cases.Case.objects.get(pk=self.receipt["case_id"]).requester_id,
            cases._digest(self.receipt["token"]),
            "CASE_ATTACHMENT",
            1,
            1,
        )

    def prepare(self, raw=RAW):
        return services.prepare_many([raw], admission=self.admission)[0]


def configure_scanner(test):
    test.scanner = SyntheticScanner()
    test.policy = ScanPolicy("SYNTHETIC-scan-policy", 2.0, 300, 64)
    configured = override_settings(
        FATWA_UPLOAD_SECURITY_ENABLED=True,
        FATWA_UPLOAD_SCAN_POLICY=test.policy,
        FATWA_UPLOAD_SCANNER=test.scanner,
        FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC=True,
    )
    configured.enable()
    test.addCleanup(configured.disable)


class ScannerMixin:
    def setUp(self):
        super().setUp()
        configure_scanner(self)
