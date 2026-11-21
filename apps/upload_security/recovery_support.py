"""Restore immutable byte evidence; require current scanner and domain authority."""

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from apps.case_attachments import services as attachments
from apps.case_attachments import tests as attachment_fixtures
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case

from . import services
from .contract import ScanPolicy
from .models import QuarantinedFile, ScanAttempt, UploadAdmission
from .test_support import SyntheticScanner

TABLES = tuple(model._meta.db_table for model in (QuarantinedFile, UploadAdmission, ScanAttempt))
FUNCTIONS = ("upload_security_history_guard()",)
TRIGGERS = (
    "upload_security_file_guard",
    "upload_security_admission_guard",
    "upload_security_scan_guard",
)
DENIALS = (
    "disabled_saved_quarantine",
    "missing_scan_policy",
    "missing_scanner",
    "synthetic_fixture_disallowed",
    "changed_engine",
    "changed_signatures",
    "changed_scan_policy",
    "expired_scan_receipt",
    "blocked_exact_bytes",
    "unscanned_exact_bytes",
    "wrong_exact_size",
    "omitted_app_with_saved_quarantine",
    "missing_current_staff",
    "foreign_case_staff",
)
RAW = b"SYNTHETIC recovery original upload\r\n  exact bytes remain private  \n"
BLOCKED = b"SYNTHETIC control-flow blocked fixture; no malware sample or AV claim\n"
POLICY = ScanPolicy("SYNTHETIC-recovery-scan-policy", 2.0, 86400, 64)


def fingerprint(value):
    return sha256(
        json.dumps(value, default=str, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def row_pins(identifiers):
    result = {}
    for query in (
        QuarantinedFile.objects.filter(pk__in=identifiers),
        UploadAdmission.objects.filter(file_id__in=identifiers),
        ScanAttempt.objects.filter(file_id__in=identifiers),
    ):
        rows = list(query.order_by("pk").values())
        if not rows:
            raise AssertionError("restored quarantine table must be nonempty")
        for row in rows:
            if "original" in row:
                row["original"] = bytes(row["original"]).hex()
        result[query.model._meta.db_table] = fingerprint(rows)
    return result


def source_pins(case_id):
    case = Case.objects.get(pk=case_id)
    attachments = list(CaseAttachment.objects.filter(case=case).order_by("pk").values())
    for row in attachments:
        if row["original"] is not None:
            row["original"] = bytes(row["original"]).hex()
    return fingerprint(
        [
            list(Case.objects.filter(pk=case.pk).values()),
            case.source.original_question,
            case.source.question_sha256,
            list(case.evidence.order_by("version").values()),
            list(case.answers.order_by("revision").values()),
            list(case.decisions.order_by("id").values()),
            list(case.events.order_by("sequence").values()),
            attachments,
        ]
    )


@contextmanager
def fresh_trust(receipt):
    scanner = SyntheticScanner()
    directory = attachment_fixtures.TestDirectory([receipt["public_ref"]])
    with override_settings(
        FATWA_CASE_ATTACHMENTS_ENABLED=True,
        FATWA_UPLOAD_SECURITY_ENABLED=True,
        FATWA_UPLOAD_SCAN_POLICY=POLICY,
        FATWA_UPLOAD_SCANNER=scanner,
        FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
    ):
        yield scanner, attachment_fixtures.staff_common(receipt, directory)


def populate():
    receipt = attachment_fixtures.new_case()
    with fresh_trust(receipt) as (scanner, _):
        saved = attachment_fixtures.upload(receipt, raw=RAW, filename="scan-recovery.txt")
        scanner.changes = {"status": "BLOCKED"}
        try:
            attachment_fixtures.upload(
                receipt,
                raw=BLOCKED,
                filename="blocked-recovery.txt",
                expected_revision=Case.objects.get(pk=receipt["case_id"]).revision,
            )
        except services.UploadSecurityDenied as exc:
            if exc.status != "BLOCKED":
                raise
        else:
            raise AssertionError("synthetic blocked file was released")
        identifiers = [sha256(raw).hexdigest() for raw in (RAW, BLOCKED)]
        return {
            "case": {key: receipt[key] for key in ("case_id", "public_ref")},
            "attachment_id": saved["id"],
            "files": identifiers,
            "tables": row_pins(identifiers),
            "sources": source_pins(receipt["case_id"]),
            "scanner_mode": "SYNTHETIC",
        }


def verify_restored(pins):
    if (
        row_pins(pins["files"]) != pins["tables"]
        or source_pins(pins["case"]["case_id"]) != pins["sources"]
    ):
        raise AssertionError("restored quarantine, history or original owner changed")
    denied = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins["case"]) as (scanner, common):
        identifier = sha256(RAW).hexdigest()

        def receipt():
            return services.require(identifier, len(RAW))

        def read():
            return attachments.staff_read(**common, attachment_id=pins["attachment_id"])

        def positive():
            if receipt()["mode"] != "SYNTHETIC" or read()["raw"] != RAW:
                raise AssertionError("restored exact original did not reopen under fresh trust")
            for raw in (RAW, BLOCKED):
                saved = QuarantinedFile.objects.get(pk=sha256(raw).hexdigest())
                services.verify(saved)
                if bytes(saved.original) != raw:
                    raise AssertionError("quarantine original bytes changed")

        def deny(name, operation=read):
            try:
                operation()
            except cases.CaseConflict:
                denied[name] += 1
            else:
                raise AssertionError("restored upload inferred durable authority: " + name)

        positive()
        for name, key, value in (
            ("disabled_saved_quarantine", "FATWA_UPLOAD_SECURITY_ENABLED", False),
            ("missing_scan_policy", "FATWA_UPLOAD_SCAN_POLICY", None),
            ("missing_scanner", "FATWA_UPLOAD_SCANNER", None),
            ("synthetic_fixture_disallowed", "FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC", False),
            (
                "changed_scan_policy",
                "FATWA_UPLOAD_SCAN_POLICY",
                replace(POLICY, validity_seconds=60),
            ),
        ):
            with override_settings(**{key: value}):
                deny(name)
        original = scanner.current
        for name, changes in (
            ("changed_engine", {"engine_version": "SYNTHETIC-engine-v2"}),
            ("changed_signatures", {"signature_digest": "0" * 64}),
        ):
            try:
                scanner.current = replace(original, **changes)
                deny(name)
            finally:
                scanner.current = original
        expired = ScanAttempt.objects.get(file_id=identifier).valid_until + timedelta(seconds=1)
        with patch.object(services.timezone, "now", return_value=expired):
            deny("expired_scan_receipt", receipt)
        deny(
            "blocked_exact_bytes",
            lambda: services.require(sha256(BLOCKED).hexdigest(), len(BLOCKED)),
        )
        unseen = b"SYNTHETIC unscanned original after restore"
        deny(
            "unscanned_exact_bytes",
            lambda: services.require(sha256(unseen).hexdigest(), len(unseen)),
        )
        deny("wrong_exact_size", lambda: services.require(identifier, len(RAW) + 1))
        with override_settings(
            INSTALLED_APPS=[
                item for item in settings.INSTALLED_APPS if item != "apps.upload_security"
            ],
            FATWA_UPLOAD_SECURITY_ENABLED=False,
        ):
            deny("omitted_app_with_saved_quarantine", receipt)
        deny(
            "missing_current_staff",
            lambda: attachments.staff_read(
                **{**common, "provider": None}, attachment_id=pins["attachment_id"]
            ),
        )
        deny(
            "foreign_case_staff",
            lambda: attachments.staff_read(
                **{**common, "provider": attachment_fixtures.TestDirectory([])},
                attachment_id=pins["attachment_id"],
            ),
        )
        positive()
        if scanner.calls:
            raise AssertionError("restored readers unexpectedly invoked an external scanner")
    if (
        row_pins(pins["files"]) != pins["tables"]
        or source_pins(pins["case"]["case_id"]) != pins["sources"]
    ):
        raise AssertionError("restored read validation mutated quarantine or canonical owners")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denied_read_count": sum(denied.values()),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
        "original_bytes_preserved": True,
        "fresh_scanner_and_domain_authority_required": True,
        "external_scan_during_restore_read": False,
        "real_engine_verified": False,
        "scanner_mode": "SYNTHETIC",
    }
