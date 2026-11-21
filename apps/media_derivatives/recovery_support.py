"""Nonempty restored job/output history; fresh current rights remain mandatory."""

import json
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.tests import Directory
from apps.mufti_review.identity import IdentityUnavailable
from apps.research_library.test_support import bind_identity_snapshot
from apps.research_workspace.tests import SyntheticRights
from apps.upload_security.contract import ScanPolicy
from apps.upload_security.test_support import SyntheticScanner

from . import execution, services
from .models import DerivativeEvent, DerivativeJob, DerivedOutput
from .sources import Source
from .test_execution import recording
from .test_support import FEATURES, Authority

TABLES = tuple(model._meta.db_table for model in (DerivativeJob, DerivativeEvent, DerivedOutput))
FUNCTIONS = ("media_derivatives_history_guard()",)
TRIGGERS = (
    "media_derivatives_job_guard",
    "media_derivatives_event_guard",
    "media_derivatives_output_guard",
)
DENIALS = (
    "derivatives_disabled",
    "missing_derivative_authority",
    "missing_current_directory",
    "revoked_derivative_read",
    "revoked_original_read",
    "missing_current_scanner",
    "changed_scan_signatures",
    "disabled_scan_with_saved_original",
    "expired_current_identity",
    "foreign_case_identity",
    "cross_actor",
    "wrong_job",
    "cancelled_not_ready",
    "unavailable_not_ready",
)
SCAN = ScanPolicy("SYNTHETIC-derivative-recovery-scan", 2.0, 86400, 64)


def fingerprint(value):
    return sha256(
        json.dumps(value, default=str, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def rows(case_id):
    result = {}
    for query in (
        DerivativeJob.objects.filter(case_id=case_id),
        DerivativeEvent.objects.filter(job__case_id=case_id),
        DerivedOutput.objects.filter(job__case_id=case_id),
    ):
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("restored derivative table is empty")
        for row in values:
            if "raw" in row:
                row["raw"] = bytes(row["raw"]).hex()
        result[query.model._meta.db_table] = fingerprint(values)
    return result


def original_pins(case_id):
    case = Case.objects.get(pk=case_id)
    sources = list(CaseAttachment.objects.filter(case=case).order_by("pk").values())
    for row in sources:
        if row["original"] is not None:
            row["original"] = bytes(row["original"]).hex()
    return fingerprint(
        [
            list(Case.objects.filter(pk=case_id).values()),
            list(case.evidence.order_by("pk").values()),
            list(case.events.order_by("pk").values()),
            sources,
        ]
    )


@contextmanager
def fresh_trust(receipt):
    directory = bind_identity_snapshot(Directory([receipt["public_ref"]]))
    authority = Authority(receipt["public_ref"])
    rights = SyntheticRights(receipt["public_ref"])
    scanner = SyntheticScanner()
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_MEDIA_DERIVATIVES_AUTHORITY": authority,
            "FATWA_MEDIA_DERIVATIVES_PROCESSOR": execution.FFmpegProcessor(
                "/usr/bin/ffmpeg", "/usr/bin/ffprobe"
            ),
            "FATWA_RESEARCH_WORKSPACE_RIGHTS": rights,
            "FATWA_STAFF_SESSIONS_ENABLED": False,
            "FATWA_UPLOAD_SECURITY_ENABLED": True,
            "FATWA_UPLOAD_SCAN_POLICY": SCAN,
            "FATWA_UPLOAD_SCANNER": scanner,
            "FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC": True,
        }
    ):
        yield (
            dict(
                case_id=receipt["case_id"],
                subject_id="editor",
                provider=directory,
                synthetic_fixtures_only=True,
            ),
            authority,
            rights,
            scanner,
        )


def populate():
    key = uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="SYNTHETIC private derivative recovery original",
        source_event_id=key,
        requester_id="requester-" + key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    with fresh_trust(receipt) as (common, _, _, _):
        attachment = attachments.upload(
            token=receipt["token"],
            raw=recording(),
            filename="recovery-original.wav",
            media_type="audio/wav",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )

        def prepare():
            return services.prepare(
                **common,
                source=Source("ATTACHMENT", attachment["id"]),
                task="AUDIO_PLAYBACK",
                request_key=uuid.uuid4(),
                expected_revision=2,
                expected_evidence_version=2,
            )

        ready = services.run_job(**common, job_id=prepare()["id"])
        if ready["state"] != "READY":
            raise AssertionError("actual ffmpeg did not populate recovery output")
        queued = prepare()
        cancelled = services.command(
            **common,
            job_id=queued["id"],
            action="CANCEL",
            request_key=uuid.uuid4(),
            expected_sequence=queued["sequence"],
        )
        with override_settings(FATWA_MEDIA_DERIVATIVES_PROCESSOR=None):
            unavailable = services.run_job(**common, job_id=prepare()["id"])
        return {
            "case": {key: receipt[key] for key in ("case_id", "public_ref")},
            "ready": ready["id"],
            "cancelled": cancelled["id"],
            "unavailable": unavailable["id"],
            "tables": rows(receipt["case_id"]),
            "originals": original_pins(receipt["case_id"]),
            "original_sha256": sha256(recording()).hexdigest(),
            "engine": DerivedOutput.objects.get(job_id=ready["id"]).engine,
        }


def verify_restored(pins):
    case_id = pins["case"]["case_id"]
    if rows(case_id) != pins["tables"] or original_pins(case_id) != pins["originals"]:
        raise AssertionError("restored job history or exact owner changed")
    checks = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins["case"]) as (common, authority, rights, scanner):

        def read(**changes):
            return services.read_output(**{**common, **changes}, job_id=pins["ready"])

        def positive():
            result = read()
            original = services.original(**common, job_id=pins["ready"])
            if (
                result["raw"] != recording()
                or original["raw"] != recording()
                or result["engine"] != pins["engine"]
                or result["engine"]["mode"] != "LOCAL_FFMPEG"
            ):
                raise AssertionError("restored actual derivative or original changed")

        def denied(name, operation=read):
            try:
                operation()
            except (cases.CaseConflict, IdentityUnavailable):
                checks[name] += 1
            else:
                raise AssertionError("restored job inferred an access grant: " + name)

        with patch.object(
            execution,
            "invoke",
            side_effect=AssertionError("restored read must not invoke a decoder"),
        ):
            positive()
            for name, key, value in (
                ("derivatives_disabled", "FATWA_MEDIA_DERIVATIVES_ENABLED", False),
                ("missing_derivative_authority", "FATWA_MEDIA_DERIVATIVES_AUTHORITY", None),
                ("missing_current_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
                ("missing_current_scanner", "FATWA_UPLOAD_SCANNER", None),
                ("disabled_scan_with_saved_original", "FATWA_UPLOAD_SECURITY_ENABLED", False),
            ):
                with override_settings(**{key: value}):
                    denied(name)
            authority.denied.add("READ")
            denied("revoked_derivative_read")
            authority.denied.clear()
            rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
            denied("revoked_original_read")
            rights.denied.clear()
            spec = scanner.current
            scanner.current = replace(spec, signature_version="SYNTHETIC-revoked-restored-source")
            denied("changed_scan_signatures")
            scanner.current = spec
            actor = common["provider"].identities["editor"]
            common["provider"].identities["editor"] = replace(
                actor, valid_until=timezone.now() - timedelta(seconds=1)
            )
            denied("expired_current_identity")
            common["provider"].identities["editor"] = replace(actor, case_keys=frozenset())
            denied("foreign_case_identity")
            common["provider"].identities["editor"] = actor
            denied("cross_actor", lambda: read(subject_id="other"))
            denied("wrong_job", lambda: services.read_output(**common, job_id=str(uuid.uuid4())))
            denied(
                "cancelled_not_ready",
                lambda: services.read_output(**common, job_id=pins["cancelled"]),
            )
            denied(
                "unavailable_not_ready",
                lambda: services.read_output(**common, job_id=pins["unavailable"]),
            )
            positive()
        if scanner.calls:
            raise AssertionError("restored output reader invoked a scanner")
    if rows(case_id) != pins["tables"] or original_pins(case_id) != pins["originals"]:
        raise AssertionError("restore reads changed immutable data")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denied_read_count": sum(checks.values()),
        "denial_checks": checks,
        "positive_reads_after_denial": True,
        "original_bytes_preserved": True,
        "processor_mode": "LOCAL_FFMPEG",
        "processing_during_restore_read": False,
        "actual_asr_provider": "UNAVAILABLE",
        "scanner_mode": "SYNTHETIC",
    }
